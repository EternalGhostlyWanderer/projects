from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

class Company(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
    )

    id: str = Field(validation_alias="SYNTHETIC_U")
    org_type: Optional[str] = Field(default=None, validation_alias="ORG_TYPE")
    ownership_type: Optional[str] = Field(
        default=None,
        validation_alias="OKFS_NAME",
    )
    age_group: Optional[str] = Field(
        default=None,
        validation_alias="COMPANY_AGE_YEARS_GRADATION",
    )
    eco_mark: Optional[str] = Field(
        default=None,
        validation_alias="ECO_MARK_LABEL",
    )
    main_okved_code: Optional[str] = Field(
        default=None,
        validation_alias="MAINOKVED_CODE",
    )
    main_okved_name: Optional[str] = Field(
        default=None,
        validation_alias="MAINOKVED_NAME",
    )
    negative_mark: Optional[float] = Field(
        default=None,
        validation_alias="NEGATIVEMARK",
    )
    employees_fns: Optional[str] = Field(
        default=None,
        validation_alias="AMOUNT_WORKERS_FNS_GRADATION",
    )
    employees_spark: Optional[str] = Field(
        default=None,
        validation_alias="AMOUNT_WORKERS_SPARK_GRADATION",
    )
    client_type: Optional[str] = Field(default=None, validation_alias="CL_TYPE")

    product_rko_mark: Optional[float] = Field(
        default=None,
        validation_alias="CL_PRODUCT_RKO_MARK",
    )
    product_gar_mark: Optional[float] = Field(
        default=None,
        validation_alias="CL_PRODUCT_GAR_MARK",
    )
    product_loa_mark: Optional[float] = Field(
        default=None,
        validation_alias="CL_PRODUCT_LOA_MARK",
    )
    product_lea_mark: Optional[float] = Field(
        default=None,
        validation_alias="CL_PRODUCT_LEA_MARK",
    )
    product_dep_mark: Optional[float] = Field(
        default=None,
        validation_alias="CL_PRODUCT_DEP_MARK",
    )
    product_zpp_mark: Optional[float] = Field(
        default=None,
        validation_alias="CL_PRODUCT_ZPP_MARK",
    )

    fts_flag: Optional[float] = Field(default=None, validation_alias="FTS_FLAG")
    fts_country: Optional[str] = Field(
        default=None,
        validation_alias="FTS_COUNTRY_NAME",
    )
    factoring_mark: Optional[float] = Field(
        default=None,
        validation_alias="FACTORING_MARK",
    )
    revenue: Optional[float] = Field(
        default=None,
        validation_alias="REVENUE_COMPANY",
    )
    group_id: Optional[str] = Field(default=None, validation_alias="GROUP_ID")
    city: Optional[str] = Field(default=None, validation_alias="CITY")
    region: Optional[str] = Field(default=None, validation_alias="REGION")