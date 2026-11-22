/**
 * Single source of truth for company branding tokens, names, and assets.
 */

export const BRAND_IDENTITY = {
  en: {
    name: "ALHARAM ALDAHABY",
    subtitle: "Engineering Consultancy",
    fullName: "ALHARAM ALDAHABY Engineering Consultancy",
    appName: "ALHARAM ALDAHABY — Engineering Advisory Workspace",
  },
  ar: {
    name: "الهرم الذهبي",
    subtitle: "للاستشارات الهندسية",
    fullName: "الهرم الذهبي للاستشارات الهندسية",
    appName: "الهرم الذهبي — مساحة العمل الاستشارية الهندسية",
  },
} as const;

export const BRAND_LOGO_URL = "/branding/logo.jpg";

export const BRAND_COLORS = {
  brown: "#5A3A1A",
  brownDark: "#432A12",
  gold: "#E0AE1B",
  goldSoft: "#F7ECC4",
  bgCream: "#FAF7F0",
  surfaceWarm: "#F4EFE4",
  borderWarm: "#E2D6BE",
  textPrimary: "#2C1D0D",
  textMuted: "#6E5841",
} as const;

export const CLASSIFICATION_DISCLAIMER = {
  en: "Classification: PRELIMINARY — Engineering support outputs require review and sign-off by a licensed engineer.",
  ar: "التصنيف: PRELIMINARY (أولي) — المخرجات استشارية مساعدة وتتطلب مراجعة واعتماد مهندس مرخص.",
} as const;
