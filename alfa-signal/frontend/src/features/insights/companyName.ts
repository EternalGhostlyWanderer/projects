export function formatCompanyName(companyId: string): string {
  const syntheticId = /^SYN_(\d+)$/.exec(companyId);
  return syntheticId ? `Компания №${syntheticId[1]}` : `Компания ${companyId}`;
}
