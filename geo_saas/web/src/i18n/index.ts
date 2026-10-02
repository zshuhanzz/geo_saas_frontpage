/**
 * i18next initialization for geo_saas web.
 *
 * UI copy truth lives in `src/i18n/locales/{zh-CN,en-US}/{ns}.json`.
 * Components consume via `useTranslation(ns)` + `t('key.path')`.
 * TypeScript resource types are declared in `./types.ts` so missing keys
 * and typos fail at compile time.
 *
 * Conventions (MUST follow — see .claude/CLAUDE.md § i18n discipline):
 *  1. Keys are semantic: `{area}.{section}.{item}` — never ordinal.
 *  2. One namespace per page area; shared words live in `common`.
 *  3. Each namespace JSON opens with a `__doc` key describing its scope.
 *  4. Edit UI copy → change JSON only. Edit structure → change tsx only.
 *  5. Page-level titles may use "中文 · English" bilingual form in zh-CN.
 */

import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import zhCommon from "./locales/zh-CN/common.json";
import zhSidebar from "./locales/zh-CN/sidebar.json";
import zhSettings from "./locales/zh-CN/settings.json";
import zhOnboarding from "./locales/zh-CN/onboarding.json";
import zhInsights from "./locales/zh-CN/insights.json";
import zhDashboards from "./locales/zh-CN/dashboards.json";
import zhAgents from "./locales/zh-CN/agents.json";
import zhContent from "./locales/zh-CN/content.json";
import zhWizard from "./locales/zh-CN/wizard.json";
import zhValidation from "./locales/zh-CN/validation.json";
import zhReports from "./locales/zh-CN/reports.json";

import enCommon from "./locales/en-US/common.json";
import enSidebar from "./locales/en-US/sidebar.json";
import enSettings from "./locales/en-US/settings.json";
import enOnboarding from "./locales/en-US/onboarding.json";
import enInsights from "./locales/en-US/insights.json";
import enDashboards from "./locales/en-US/dashboards.json";
import enAgents from "./locales/en-US/agents.json";
import enContent from "./locales/en-US/content.json";
import enWizard from "./locales/en-US/wizard.json";
import enValidation from "./locales/en-US/validation.json";
import enReports from "./locales/en-US/reports.json";

export const SUPPORTED_LANGUAGES = ["zh-CN", "en-US"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const DEFAULT_LANGUAGE: SupportedLanguage = "zh-CN";

export const NAMESPACES = [
    "common",
    "sidebar",
    "settings",
    "onboarding",
    "insights",
    "dashboards",
    "agents",
    "content",
    "wizard",
    "validation",
    "reports",
] as const;

export const resources = {
    "zh-CN": {
        common: zhCommon,
        sidebar: zhSidebar,
        settings: zhSettings,
        onboarding: zhOnboarding,
        insights: zhInsights,
        dashboards: zhDashboards,
        agents: zhAgents,
        content: zhContent,
        wizard: zhWizard,
        validation: zhValidation,
        reports: zhReports,
    },
    "en-US": {
        common: enCommon,
        sidebar: enSidebar,
        settings: enSettings,
        onboarding: enOnboarding,
        insights: enInsights,
        dashboards: enDashboards,
        agents: enAgents,
        content: enContent,
        wizard: enWizard,
        validation: enValidation,
        reports: enReports,
    },
} as const;

void i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
        resources,
        fallbackLng: DEFAULT_LANGUAGE,
        supportedLngs: SUPPORTED_LANGUAGES,
        ns: NAMESPACES as unknown as string[],
        defaultNS: "common",
        detection: {
            order: ["localStorage", "navigator"],
            lookupLocalStorage: "geo-saas-lang",
            caches: ["localStorage"],
        },
        interpolation: {
            escapeValue: false,
        },
        returnNull: false,
    });

export default i18n;
