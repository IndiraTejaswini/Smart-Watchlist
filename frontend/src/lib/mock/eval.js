export const mockEvalFunnel = () => ({
  evaluated: 41,
  corporate_action: 2,
  market_wide: 11,
  sector_grouped: 4,
  below_cap: 20,
  surfaced: 4,
});

export const mockEvalCases = () => [
  { symbol: "IDEA", event: "1:1 Bonus Issue", naive_change_pct: -50, system_title: "Corporate action baseline adjustment", system_text: "The ex-date adjustment explains the price step; no regular alert is emitted." },
  { symbol: "TATASTEEL", event: "1:5 Stock Split", naive_change_pct: -80, system_title: "Corporate action baseline adjustment", system_text: "The split factor is applied before abnormality scoring; no regular alert is emitted." },
  { symbol: "IT sector", event: "Sympathetic sector movement", naive_change_pct: -3.9, system_title: "One grouped sector narrative", system_text: "Four constituent movements share the same sector context and are grouped." },
];

export const mockEvalContinuation = () => [
  { category: "Explained by Filing", n: 18, mean_ar: 0.004, median_ar: 0.002, same_direction_pct: 0.5 },
  { category: "Unexplained Abnormal Movement", n: 22, mean_ar: 0.017, median_ar: 0.013, same_direction_pct: 0.68 },
];
