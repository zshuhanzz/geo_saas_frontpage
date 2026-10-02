import { FileText } from "lucide-react";
import { useTranslation } from "react-i18next";

type ContentTypeKey = "faq" | "aeo_article" | "article" | "brief" | "comparison" | "platform_post" | "howto" | "listicle";

const CONTENT_TYPE_DEFS: { id: ContentTypeKey; icon: string }[] = [
  { id: "faq", icon: "📋" },
  { id: "aeo_article", icon: "🤖" },
  { id: "article", icon: "✍️" },
  { id: "brief", icon: "📝" },
  { id: "comparison", icon: "⚖️" },
  { id: "platform_post", icon: "📱" },
  { id: "howto", icon: "📖" },
  { id: "listicle", icon: "📋" },
];

interface NodeContentTypeProps {
  value: string;
  onChange: (contentType: string) => void;
}

export default function NodeContentType({ value, onChange }: NodeContentTypeProps) {
  const { t } = useTranslation("content");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-5 h-5 text-purple-400" />
        <h3 className="text-lg font-semibold text-foreground">{t("nodes.contentType.title")}</h3>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {CONTENT_TYPE_DEFS.map((ct) => (
          <button
            key={ct.id}
            onClick={() => onChange(ct.id)}
            className={`p-3 rounded-lg border text-left transition-colors ${
              value === ct.id
                ? "border-purple-500/50 bg-purple-500/10 text-foreground"
                : "border-border bg-muted/50 text-muted-foreground hover:border-border/80"
            }`}
          >
            <div className="flex items-center gap-2">
              <span>{ct.icon}</span>
              <span className="font-medium text-sm">{t(`nodes.contentType.items.${ct.id}.label`)}</span>
            </div>
            <p className="text-xs mt-1 opacity-70">{t(`nodes.contentType.items.${ct.id}.desc`)}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
