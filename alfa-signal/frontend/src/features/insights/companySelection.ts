import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { fetchCompanies } from "@/features/insights/dataSource";
import type { CompanyProfile } from "@/features/insights/model";
import { insightQueryKeys } from "@/features/insights/queries";

const STORAGE_KEY = "alfa-signal-company";
const NO_COMPANIES: CompanyProfile[] = [];

function readStoredCompanyId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeCompanyId(companyId: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, companyId);
  } catch {
    /* Без localStorage компания всё равно сохраняется в адресе страницы. */
  }
}

export function useCompanySelection() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const companiesQuery = useQuery({
    queryKey: insightQueryKeys.companies(),
    queryFn: fetchCompanies,
    staleTime: Infinity,
  });
  const companies = companiesQuery.data ?? NO_COMPANIES;
  const requestedCompanyId = searchParams.get("company");
  const storedCompanyId = readStoredCompanyId();
  const selectedCompany =
    companies.find((company) => company.companyId === requestedCompanyId) ??
    companies.find((company) => company.companyId === storedCompanyId) ??
    companies[0];
  const selectedCompanyId = selectedCompany?.companyId ?? "";

  function selectCompany(companyId: string) {
    if (!companies.some((company) => company.companyId === companyId)) return;
    storeCompanyId(companyId);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("company", companyId);
    nextParams.delete("profile");
    const pathname = location.pathname.startsWith("/insights/") ? "/insights" : location.pathname;
    const search = nextParams.toString();
    navigate({ pathname, search: search ? `?${search}` : "" });
  }

  return {
    companies,
    companiesQuery,
    selectedCompany,
    selectedCompanyId,
    selectCompany,
  };
}
