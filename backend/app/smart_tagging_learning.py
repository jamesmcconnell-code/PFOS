"""Local historical consensus suggestions for transactions without an explicit rule."""
import json
from collections import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Account, Tag, Transaction, TransactionClassificationSuggestion, TransactionClassificationSuggestionTag, TransactionTag
from .smart_tagging import normalize_merchant_key

MIN_EVIDENCE=3
HIGH_CONFIDENCE=.9

def _effective_owner(transaction, account): return transaction.owner_id or account.owner_id
def _historical_matches(transaction, db: Session):
    account=db.get(Account,transaction.account_id); key=normalize_merchant_key(transaction.description); direction=1 if float(transaction.amount)>0 else -1; owner=_effective_owner(transaction,account)
    candidates=db.scalars(select(Transaction).join(Account,Account.id==Transaction.account_id).where(Transaction.household_id==transaction.household_id,Transaction.id!=transaction.id,Transaction.is_pending==False)).all()
    result=[]
    for item in candidates:
        other_account=db.get(Account,item.account_id)
        if normalize_merchant_key(item.description)!=key or (1 if float(item.amount)>0 else -1)!=direction or other_account.account_type!=account.account_type: continue
        if _effective_owner(item,other_account)!=owner: continue
        result.append(item)
    return result,key

def _consensus(values):
    counts=Counter(value for value in values if value is not None); total=len(values)
    if not counts or not total: return None,0,0
    value,count=counts.most_common(1)[0]
    return value,count,count/total

def generate_historical_suggestion(transaction: Transaction, db: Session):
    """Return an existing/new local suggestion, or an insufficient-history result.

    This function never applies classifications. It intentionally excludes all
    planner-impacting fields and split allocations from learned output.
    """
    existing=db.scalar(select(TransactionClassificationSuggestion).where(TransactionClassificationSuggestion.transaction_id==transaction.id).order_by(TransactionClassificationSuggestion.created_at.desc()))
    if existing: return existing
    matches,key=_historical_matches(transaction,db)
    if len(matches)<MIN_EVIDENCE:
        return {'result':'insufficient_history','normalized_merchant_key':key,'evidence_count':len(matches),'explanation':f'Only {len(matches)} prior matching {key} transactions exist; at least {MIN_EVIDENCE} are required.'}
    total=len(matches); fields={}; category,count,confidence=_consensus([item.category_id for item in matches])
    if category and confidence>=.5:
        fields['category_id']={'value':str(category),'count':count,'total':total,'confidence':confidence,'explanation':f'{count} of {total} prior matching {key} transactions used the same category.'}
    essential,count,confidence=_consensus([item.is_essential for item in matches])
    if confidence>=.5:
        fields['essential']={'value':essential,'count':count,'total':total,'confidence':confidence,'explanation':f'{count} of {total} prior matching {key} transactions shared the essential flag.'}
    recurring,count,confidence=_consensus([item.is_recurring for item in matches])
    if confidence>=.5:
        fields['recurring']={'value':recurring,'count':count,'total':total,'confidence':confidence,'explanation':f'{count} of {total} prior matching {key} transactions shared the recurring flag.'}
    tag_counts=Counter(tag_id for item in matches for tag_id in db.scalars(select(TransactionTag.tag_id).where(TransactionTag.transaction_id==item.id)).all())
    strong_tags=[tag_id for tag_id,count in tag_counts.items() if count/total>=.8]
    if strong_tags:
        fields['tag_ids']={'value':[str(tag_id) for tag_id in strong_tags],'count':min(tag_counts[tag_id] for tag_id in strong_tags),'total':total,'confidence':min(tag_counts[tag_id]/total for tag_id in strong_tags),'explanation':f'Common tags appeared on at least 80% of {total} prior matching {key} transactions.'}
    owner,count,confidence=_consensus([item.owner_id for item in matches])
    if owner and confidence>=.8:
        fields['owner_id']={'value':str(owner),'count':count,'total':total,'confidence':confidence,'explanation':f'{count} of {total} prior matching {key} transactions had the same assigned owner.'}
    if not fields:
        return {'result':'insufficient_history','normalized_merchant_key':key,'evidence_count':total,'explanation':f'{total} prior matching {key} transactions exist, but their classifications conflict and no value meets the evidence threshold.'}
    confidences=[field['confidence'] for field in fields.values()]; score=sum(confidences)/len(confidences); category_id=category if 'category_id' in fields else None
    suggestion=TransactionClassificationSuggestion(household_id=transaction.household_id,transaction_id=transaction.id,category_id=category_id,owner_id=owner if 'owner_id' in fields else None,essential=essential if 'essential' in fields else None,recurring=recurring if 'recurring' in fields else None,confidence_score=score,explanation=' '.join(field['explanation'] for field in fields.values()),proposal_data=json.dumps({'normalized_merchant_key':key,'fields':fields}),evidence_data=json.dumps({'matching_transactions':total}),source_type='learned',status='pending',safe_for_auto_apply=score>=HIGH_CONFIDENCE and all(name in {'category_id','tag_ids','owner_id','essential','recurring'} for name in fields))
    db.add(suggestion);db.flush()
    for tag_id in strong_tags: db.add(TransactionClassificationSuggestionTag(suggestion_id=suggestion.id,tag_id=tag_id))
    return suggestion
