/**
 * TypeScript resource typing for i18next.
 *
 * Using zh-CN as the canonical shape source: any key that exists in zh-CN
 * but not in en-US (or vice versa) will still type-check, but `t()` calls
 * with unknown keys will fail compilation. Keep the two locales structurally
 * aligned — run `npm run i18n:check` (TODO: add in B6) to catch drift in CI.
 */

import "i18next";

import type common from "./locales/zh-CN/common.json";
import type sidebar from "./locales/zh-CN/sidebar.json";
import type settings from "./locales/zh-CN/settings.json";
import type onboarding from "./locales/zh-CN/onboarding.json";
import type insights from "./locales/zh-CN/insights.json";
import type dashboards from "./locales/zh-CN/dashboards.json";
import type agents from "./locales/zh-CN/agents.json";
import type content from "./locales/zh-CN/content.json";
import type wizard from "./locales/zh-CN/wizard.json";
import type validation from "./locales/zh-CN/validation.json";
import type reports from "./locales/zh-CN/reports.json";

declare module "i18next" {
    interface CustomTypeOptions {
        defaultNS: "common";
        resources: {
            common: typeof common;
            sidebar: typeof sidebar;
            settings: typeof settings;
            onboarding: typeof onboarding;
            insights: typeof insights;
            dashboards: typeof dashboards;
            agents: typeof agents;
            content: typeof content;
            wizard: typeof wizard;
            validation: typeof validation;
            reports: typeof reports;
        };
        returnNull: false;
    }
}
