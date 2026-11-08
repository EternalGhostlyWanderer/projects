import type {
  AnalysisContext,
  BusinessInsight,
  CompanyProfile,
  Evidence,
  EvidenceType,
  InsightKind,
  InsightsWorkspace,
  PriorityAction,
  RelevanceLevel,
} from "@/features/insights/model";

type DemoInsightRecord = {
  id: string;
  companyId: string;
  title: string;
  detailTitle?: string;
  category: string;
  publishedAt: string;
  analyzedAt: string;
  relevanceLevel: RelevanceLevel;
  kind: InsightKind;
  eventSummary: string;
  cardSummary: string;
  attentionLabel: string;
  provenanceLabel: string;
  cardCaveat?: string;
  relevanceReasons: string[];
  decisionQuestion: string;
  mechanism: string;
  primaryEffect: string;
  risks: string[];
  opportunities: string[];
  nextSteps: string[];
  unknowns: string[];
  evidence: Array<{
    id: string;
    type: EvidenceType;
    text: string;
    sourceId?: string;
    sourceTitle?: string;
    sourceUrl?: string;
    sourceDate?: string;
    sourcePage?: string;
  }>;
};

const demoCompanies: CompanyProfile[] = [
  {
    companyId: "company-001",
    groupId: null,
    name: "Компания №001",
    industry: "Производство",
    region: "Москва",
    profileLabel: "Демо-профиль",
    businessFeatures: ["Кредитные продукты", "Внешняя торговля"],
    sensitivityFactors: ["Стоимость финансирования", "Сроки международных расчётов"],
    missingData: [
      "Размер и структура задолженности",
      "Сроки пересмотра кредитных ставок",
      "Страны и валюты действующих контрактов",
    ],
    contextSources: ["Продуктовый профиль", "Отрасль и регион", "Демо-признаки бизнеса"],
  },
  {
    companyId: "company-002",
    groupId: null,
    name: "Компания №002",
    industry: "Розничная торговля",
    region: "Казань",
    profileLabel: "Демо-профиль",
    businessFeatures: ["Эквайринг", "Сезонная выручка"],
    sensitivityFactors: ["Комиссия эквайринга", "Стоимость сезонной логистики"],
    missingData: [
      "Фактический месячный оборот по картам",
      "Условия действующего тарифа эквайринга",
      "Плановый объём сезонных поставок",
    ],
    contextSources: ["Продуктовый профиль", "Отрасль и регион", "Демо-признаки бизнеса"],
  },
];

const demoInsightRecords: DemoInsightRecord[] = [
  {
    id: "key-rate-impact",
    companyId: "company-001",
    title: "Ставка сохранена: пересмотрите план новых заимствований",
    detailTitle: "Ставка сохранена: что это меняет для компании",
    category: "Макроэкономика",
    publishedAt: "2026-10-23T09:00:00+03:00",
    analyzedAt: "2026-10-23T11:30:00+03:00",
    relevanceLevel: "high",
    kind: "risk",
    eventSummary: "Демо-сценарий: ключевая ставка сохранена на текущем уровне.",
    cardSummary:
      "У компании есть кредитные продукты. Удешевление нового финансирования может отложиться.",
    attentionLabel: "Высокая значимость",
    provenanceLabel: "Позиция банка не установлена",
    cardCaveat: "Сроки пересмотра ставок неизвестны.",
    relevanceReasons: ["Кредитные продукты", "Чувствительность к стоимости финансирования"],
    decisionQuestion: "Когда банк пересматривает условия действующих и новых кредитных линий?",
    mechanism:
      "Сохранение ключевой ставки → стоимость фондирования банков → цена нового финансирования",
    primaryEffect:
      "Стоимость нового финансирования может снижаться медленнее, чем заложено в план.",
    risks: [
      "Если компания планирует новое заимствование, условия могут оставаться выше заложенных в план.",
    ],
    opportunities: [
      "Условная возможность: пересмотреть сроки привлечения средств после уточнения кредитного графика.",
    ],
    nextSteps: [
      "Проверить график пересмотра кредитных условий.",
      "Сверить планы капитальных затрат с доступными лимитами финансирования.",
    ],
    unknowns: [
      "Размер задолженности",
      "Тип ставки по договорам",
      "Сроки пересмотра условий",
      "Планы нового финансирования",
    ],
    evidence: [
      {
        id: "key-rate-profile-fact",
        type: "FACT",
        text: "В демо-профиле компании указан кредитный продукт.",
        sourceId: "demo-company-profile",
        sourceTitle: "Демо-профиль компании №001",
      },
      {
        id: "key-rate-ai-mechanism",
        type: "AI_INFERENCE",
        text: "Событие связано с компанией через возможное изменение стоимости нового заёмного капитала.",
      },
      {
        id: "key-rate-hypothesis",
        type: "HYPOTHESIS",
        text: "Снижение стоимости нового финансирования может происходить медленнее ожидаемого.",
      },
    ],
  },
  {
    id: "trade-conditions",
    companyId: "company-001",
    title: "Изменились требования к международным расчётам",
    category: "Внешняя торговля",
    publishedAt: "2026-10-23T08:20:00+03:00",
    analyzedAt: "2026-10-23T11:10:00+03:00",
    relevanceLevel: "high",
    kind: "risk",
    eventSummary: "Демо-сценарий: изменились требования к отдельным внешнеторговым расчётам.",
    cardSummary:
      "Событие может затронуть ваши внешнеторговые операции. Уточните страны и валюты контрактов.",
    attentionLabel: "Средняя значимость",
    provenanceLabel: "Нужны данные компании",
    relevanceReasons: ["Внешняя торговля", "Чувствительность к срокам международных расчётов"],
    decisionQuestion:
      "Какие ближайшие контракты зависят от текущего маршрута международного платежа?",
    mechanism: "Изменение правил расчётов → срок платежа → потребность в оборотном капитале",
    primaryEffect: "Срок прохождения отдельных международных платежей может увеличиться.",
    risks: ["Задержка поступлений может временно увеличить потребность в ликвидности."],
    opportunities: [
      "Условная возможность: заранее согласовать резервный маршрут после проверки стран и валют контрактов.",
    ],
    nextSteps: [
      "Проверить ближайшие даты международных платежей.",
      "Уточнить доступность резервных маршрутов расчётов.",
    ],
    unknowns: [
      "Страны и валюты контрактов",
      "Текущие маршруты платежей",
      "Размер доступного резерва ликвидности",
    ],
    evidence: [
      {
        id: "trade-profile-fact",
        type: "FACT",
        text: "В демо-профиле компании указана внешнеторговая деятельность.",
        sourceId: "demo-company-profile",
        sourceTitle: "Демо-профиль компании №001",
      },
      {
        id: "trade-ai-mechanism",
        type: "AI_INFERENCE",
        text: "Изменение срока платежа может повлиять на оборотный капитал компании.",
      },
      {
        id: "trade-hypothesis",
        type: "HYPOTHESIS",
        text: "Отдельные действующие контракты могут потребовать резервного маршрута расчётов.",
      },
    ],
  },
  {
    id: "liquidity-placement",
    companyId: "company-001",
    title: "Свободные средства: сравните условия размещения",
    category: "Ликвидность",
    publishedAt: "2026-10-22T10:20:00+03:00",
    analyzedAt: "2026-10-23T09:40:00+03:00",
    relevanceLevel: "medium",
    kind: "opportunity",
    eventSummary:
      "Демо-сценарий: рыночные условия размещения средств изменились относительно предыдущего периода.",
    cardSummary: "Для оценки возможности нужен прогноз остатков и ближайших платежей компании.",
    attentionLabel: "Возможность",
    provenanceLabel: "Условный вывод",
    relevanceReasons: ["Финансовый контекст требует уточнения"],
    decisionQuestion:
      "Есть ли прогнозируемый остаток, который не потребуется для ближайших платежей?",
    mechanism: "Изменение ставок → условия размещения → потенциальная доходность остатка",
    primaryEffect:
      "Условия размещения могут быть релевантны только при наличии подтверждённого свободного остатка.",
    risks: ["Без прогноза платежей нельзя считать остаток свободным для размещения."],
    opportunities: [
      "Условная возможность: сравнить условия размещения после подтверждения прогноза ликвидности.",
    ],
    nextSteps: [
      "Сформировать прогноз остатков и ближайших платежей.",
      "Сравнить доступные сроки и условия размещения.",
    ],
    unknowns: ["Прогноз остатков", "Ближайшие платежи", "Допустимый срок размещения"],
    evidence: [
      {
        id: "liquidity-ai-mechanism",
        type: "AI_INFERENCE",
        text: "Релевантность условий размещения зависит от подтверждённого прогноза ликвидности.",
      },
      {
        id: "liquidity-hypothesis",
        type: "HYPOTHESIS",
        text: "У компании может быть остаток, доступный для краткосрочного размещения.",
      },
    ],
  },
  {
    id: "acquiring-growth",
    companyId: "company-002",
    title: "Рост карточного оборота может открыть более выгодную тарифную ступень",
    category: "Платежи",
    publishedAt: "2026-10-22T14:00:00+03:00",
    analyzedAt: "2026-10-23T10:40:00+03:00",
    relevanceLevel: "medium",
    kind: "opportunity",
    eventSummary: "Демо-сценарий: доля безналичных платежей в розничном обороте растёт.",
    cardSummary:
      "Рост карточного оборота может открыть более выгодную тарифную ступень эквайринга.",
    attentionLabel: "Возможность",
    provenanceLabel: "Нужны данные компании",
    relevanceReasons: ["Эквайринг", "Сезонная выручка"],
    decisionQuestion: "Достигнет ли прогнозный оборот следующего порога тарифной сетки?",
    mechanism: "Рост карточного оборота → тарифная ступень → комиссия эквайринга",
    primaryEffect: "При достижении нового порога может стать доступен более выгодный тариф.",
    risks: ["Без проверки тарифа комиссия может расти пропорционально сезонному обороту."],
    opportunities: [
      "Условная возможность: запросить пересмотр тарифа, если прогнозный оборот достигает нужного порога.",
    ],
    nextSteps: [
      "Сопоставить прогноз карточного оборота с тарифной сеткой.",
      "Уточнить срок действия текущих условий эквайринга.",
    ],
    unknowns: ["Фактический оборот по картам", "Порог тарифной сетки", "Текущая комиссия"],
    evidence: [
      {
        id: "acquiring-profile-fact",
        type: "FACT",
        text: "В демо-профиле компании указаны эквайринг и сезонная выручка.",
        sourceId: "demo-company-profile",
        sourceTitle: "Демо-профиль компании №002",
      },
      {
        id: "acquiring-ai-mechanism",
        type: "AI_INFERENCE",
        text: "Сезонный рост карточного оборота может изменить применимую тарифную ступень.",
      },
      {
        id: "acquiring-hypothesis",
        type: "HYPOTHESIS",
        text: "Прогнозный оборот может быть достаточен для запроса новых условий.",
      },
    ],
  },
  {
    id: "seasonal-logistics",
    companyId: "company-002",
    title: "Рост стоимости доставки может снизить маржинальность сезонного ассортимента",
    category: "Логистика",
    publishedAt: "2026-10-22T12:30:00+03:00",
    analyzedAt: "2026-10-23T10:20:00+03:00",
    relevanceLevel: "high",
    kind: "risk",
    eventSummary: "Демо-сценарий: тарифы грузовых перевозок растут перед сезонным пиком.",
    cardSummary: "Логистические расходы могут превысить уровень, заложенный в сезонный план.",
    attentionLabel: "Средняя значимость",
    provenanceLabel: "Условный вывод",
    relevanceReasons: ["Сезонная выручка", "Чувствительность к стоимости логистики"],
    decisionQuestion: "Какая часть сезонных поставок ещё не зафиксирована по тарифу?",
    mechanism: "Рост тарифов перевозчиков → стоимость доставки → маржинальность ассортимента",
    primaryEffect: "Логистические расходы могут превысить уровень, заложенный в сезонный план.",
    risks: ["Маржинальность сезонного ассортимента может снизиться при неизменных ценах продажи."],
    opportunities: [
      "Условная возможность: зафиксировать часть объёмов заранее, если договоры допускают бронирование.",
    ],
    nextSteps: [
      "Сопоставить договорные тарифы с плановым объёмом поставок.",
      "Проверить доступность раннего бронирования у перевозчиков.",
    ],
    unknowns: ["Договорные тарифы", "Плановый объём поставок", "Доля логистики в себестоимости"],
    evidence: [
      {
        id: "logistics-profile-fact",
        type: "FACT",
        text: "В демо-профиле компании указана сезонная выручка.",
        sourceId: "demo-company-profile",
        sourceTitle: "Демо-профиль компании №002",
      },
      {
        id: "logistics-ai-mechanism",
        type: "AI_INFERENCE",
        text: "Рост стоимости доставки может повлиять на маржинальность сезонного ассортимента.",
      },
      {
        id: "logistics-hypothesis",
        type: "HYPOTHESIS",
        text: "Часть будущих поставок может быть доступна для раннего бронирования.",
      },
    ],
  },
];

const demoPriorityActions: PriorityAction[] = [
  {
    companyId: "company-001",
    insightId: "key-rate-impact",
    title: "Проверить график пересмотра кредитных условий",
    rationale:
      "Действующий кредитный продукт подтверждён профилем, но тип ставки и дата пересмотра неизвестны.",
  },
  {
    companyId: "company-002",
    insightId: "acquiring-growth",
    title: "Сверить прогноз оборота с тарифной сеткой",
    rationale:
      "Эквайринг и сезонность подтверждены профилем, но текущий оборот и тарифный порог неизвестны.",
  },
];

function adaptEvidence(evidence: DemoInsightRecord["evidence"][number]): Evidence {
  return { ...evidence };
}

function adaptInsight(record: DemoInsightRecord): BusinessInsight {
  const evidence = record.evidence.map(adaptEvidence);

  return {
    id: record.id,
    companyId: record.companyId,
    groupId: null,
    title: record.title,
    detailTitle: record.detailTitle,
    category: record.category,
    publishedAt: record.publishedAt,
    analyzedAt: record.analyzedAt,
    relevanceLevel: record.relevanceLevel,
    kind: record.kind,
    eventSummary: record.eventSummary,
    cardSummary: record.cardSummary,
    attentionLabel: record.attentionLabel,
    provenanceLabel: record.provenanceLabel,
    cardCaveat: record.cardCaveat,
    relevanceReasons: [...record.relevanceReasons],
    decisionQuestion: record.decisionQuestion,
    impact: {
      mechanism: record.mechanism,
      primaryEffect: record.primaryEffect,
      risks: [...record.risks],
      opportunities: [...record.opportunities],
      nextSteps: [...record.nextSteps],
      unknowns: [...record.unknowns],
      evidenceIds: evidence.map((item) => item.id),
    },
    evidence,
  };
}

function waitForDemoData() {
  return new Promise<void>((resolve) => window.setTimeout(resolve, 250));
}

export function listDemoCompanies(): CompanyProfile[] {
  return demoCompanies.map((company) => ({
    ...company,
    businessFeatures: [...company.businessFeatures],
    sensitivityFactors: [...company.sensitivityFactors],
    missingData: [...company.missingData],
    contextSources: [...company.contextSources],
  }));
}

export async function fetchDemoInsightsWorkspace(
  context: AnalysisContext,
): Promise<InsightsWorkspace> {
  await waitForDemoData();

  if (context.groupId !== null) {
    throw new Error("Групповой режим аналитики пока не поддерживается.");
  }

  const company = demoCompanies.find((item) => item.companyId === context.companyId);

  if (!company) {
    throw new Error("Профиль выбранной компании не найден.");
  }

  return {
    context,
    company: listDemoCompanies().find((item) => item.companyId === context.companyId) ?? company,
    insights: demoInsightRecords
      .filter((record) => record.companyId === context.companyId)
      .map(adaptInsight),
    priorityAction:
      demoPriorityActions.find((action) => action.companyId === context.companyId) ?? null,
  };
}

export async function fetchDemoInsight(insightId: string): Promise<BusinessInsight> {
  await waitForDemoData();
  const record = demoInsightRecords.find((item) => item.id === insightId);

  if (!record) {
    throw new Error("Инсайт не найден или недоступен в демо-режиме.");
  }

  return adaptInsight(record);
}

export function getDemoCompany(companyId: string): CompanyProfile | null {
  return listDemoCompanies().find((company) => company.companyId === companyId) ?? null;
}
