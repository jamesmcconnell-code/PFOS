export const financialPrivacyKey = 'pfos_blur_financial_numbers';
export function applyFinancialPrivacy(enabled: boolean) {
  document.documentElement.dataset.blurFinancial = String(enabled);
  localStorage.setItem(financialPrivacyKey, String(enabled));
  window.dispatchEvent(new Event('pfos-financial-privacy-change'));
}
