"""Deterministic, local-only classification for newly created transactions."""
import re
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from .models import Account, MerchantIdentity, Tag, Transaction, TransactionClassificationRule, TransactionClassificationRuleTag, TransactionClassificationSuggestion, TransactionClassificationSuggestionTag, TransactionTag

PLANNER_FIELDS=('internal_transfer','refund_credit','loan_reimbursement','expected','prorated','proration_months')

def normalize_merchant_key(description: str) -> str:
    value=' '.join((description or '').strip().lower().split())
    value=re.sub(r'\s+(?:ref(?:erence)?|confirmation|trace)\s*(?:#|id)?\s*[a-z0-9-]{5,}\b.*$','',value,flags=re.I)
    value=re.sub(r'\s+on\s+\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b','',value,flags=re.I)
    return ' '.join(value.split())

def merchant_identity_for(transaction: Transaction, db: Session) -> MerchantIdentity:
    key=normalize_merchant_key(transaction.description)
    identity=db.scalar(select(MerchantIdentity).where(MerchantIdentity.household_id==transaction.household_id,MerchantIdentity.normalized_merchant_key==key))
    if not identity:
        identity=MerchantIdentity(household_id=transaction.household_id,normalized_merchant_key=key,display_name=transaction.description.strip()[:255] or key)
        db.add(identity);db.flush()
    return identity

def _rule_matches(rule, transaction, account, merchant_key):
    effective_owner=transaction.owner_id or account.owner_id
    if rule.owner_id and rule.owner_id!=effective_owner: return False
    if rule.account_id and rule.account_id!=transaction.account_id: return False
    if rule.financial_role and rule.financial_role!=account.account_type: return False
    if rule.direction=='credit' and float(transaction.amount)<=0: return False
    if rule.direction=='debit' and float(transaction.amount)>=0: return False
    if rule.normalized_merchant_key and rule.normalized_merchant_key!=merchant_key: return False
    if rule.description_pattern:
        try:
            if not re.search(rule.description_pattern,transaction.description,re.I): return False
        except re.error: return False
    return True

def _specificity(rule):
    return sum(bool(value) for value in (rule.owner_id,rule.account_id,rule.financial_role,rule.normalized_merchant_key,rule.description_pattern))+(rule.direction!='any')

def matching_rule(transaction: Transaction, db: Session):
    account=db.get(Account,transaction.account_id);merchant=merchant_identity_for(transaction,db)
    rules=db.scalars(select(TransactionClassificationRule).where(TransactionClassificationRule.household_id==transaction.household_id,TransactionClassificationRule.is_active==True)).all()
    matches=[rule for rule in rules if _rule_matches(rule,transaction,account,merchant.normalized_merchant_key)]
    return (sorted(matches,key=lambda rule:(rule.priority,-_specificity(rule),rule.created_at))[0] if matches else None),merchant,account

def _rule_tag_ids(rule_id, db): return list(db.scalars(select(TransactionClassificationRuleTag.tag_id).where(TransactionClassificationRuleTag.rule_id==rule_id)).all())
def _planner_outputs(rule): return any(getattr(rule,field) is not None for field in PLANNER_FIELDS)
def _apply(transaction, rule, db, include_planner, override_import_category=False, preserve_fields=frozenset()):
    if rule.category_id and 'category_id' not in preserve_fields and (transaction.category_id is None or override_import_category): transaction.category_id=rule.category_id
    account=db.get(Account,transaction.account_id)
    if 'owner_id' not in preserve_fields and transaction.owner_id is None and rule.classified_owner_id and (account.ownership!='individual' or account.owner_id==rule.classified_owner_id): transaction.owner_id=rule.classified_owner_id
    if rule.essential is not None and 'is_essential' not in preserve_fields: transaction.is_essential=rule.essential
    for tag_id in _rule_tag_ids(rule.id,db):
        if not db.get(TransactionTag,(transaction.id,tag_id)): db.add(TransactionTag(transaction_id=transaction.id,tag_id=tag_id))
    if include_planner:
        if rule.internal_transfer is not None: transaction.is_internal_transfer=rule.internal_transfer
        if rule.refund_credit is not None: transaction.is_refund=rule.refund_credit
        if rule.expected is not None: transaction.is_expected=rule.expected
        if rule.prorated is not None: transaction.is_prorated=rule.prorated
        if rule.proration_months is not None: transaction.proration_months=rule.proration_months
        if rule.loan_reimbursement:
            tag=db.scalar(select(Tag).where(Tag.household_id==transaction.household_id,func.lower(Tag.name)=='loan reimbursement'))
            if not tag:
                tag=Tag(household_id=transaction.household_id,name='Loan reimbursement');db.add(tag);db.flush()
            if not db.get(TransactionTag,(transaction.id,tag.id)): db.add(TransactionTag(transaction_id=transaction.id,tag_id=tag.id))

def evaluate_new_transaction(transaction: Transaction, db: Session, source: str='import', preserve_fields=frozenset()):
    """Classify only a just-created transaction. Never scans or rewrites history."""
    rule,merchant,_=matching_rule(transaction,db)
    if not rule: return None
    planner_outputs=_planner_outputs(rule);auto_apply=not planner_outputs or rule.planner_automation_approved
    explanation=f"Matched local rule '{rule.name}' by merchant '{merchant.normalized_merchant_key}' (priority {rule.priority})."
    suggestion=TransactionClassificationSuggestion(household_id=transaction.household_id,transaction_id=transaction.id,rule_id=rule.id,category_id=rule.category_id,owner_id=rule.classified_owner_id,essential=rule.essential,internal_transfer=rule.internal_transfer,refund_credit=rule.refund_credit,loan_reimbursement=rule.loan_reimbursement,expected=rule.expected,prorated=rule.prorated,proration_months=rule.proration_months,confidence_score=1,explanation=explanation,status='applied' if auto_apply else 'pending',safe_for_auto_apply=auto_apply)
    db.add(suggestion);db.flush()
    for tag_id in _rule_tag_ids(rule.id,db): db.add(TransactionClassificationSuggestionTag(suggestion_id=suggestion.id,tag_id=tag_id))
    if auto_apply:
        _apply(transaction,rule,db,include_planner=True,override_import_category=source!='manual',preserve_fields=preserve_fields);transaction.classification_rule_id=rule.id;transaction.classification_explanation=explanation
    return suggestion

def apply_suggestion(suggestion: TransactionClassificationSuggestion, db: Session):
    transaction=db.get(Transaction,suggestion.transaction_id);rule=db.get(TransactionClassificationRule,suggestion.rule_id) if suggestion.rule_id else None
    if not transaction or not rule: return None
    _apply(transaction,rule,db,include_planner=True,override_import_category=True);transaction.classification_rule_id=rule.id;transaction.classification_explanation=suggestion.explanation;suggestion.status='applied';suggestion.safe_for_auto_apply=False
    return transaction

def latest_suggestion(transaction_id, db):
    return db.scalar(select(TransactionClassificationSuggestion).where(TransactionClassificationSuggestion.transaction_id==transaction_id).order_by(TransactionClassificationSuggestion.created_at.desc()))
