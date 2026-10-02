import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";

export default function DraftProductAdder({ onAdd }: { onAdd: (value: string) => void }) {
    const { t } = useTranslation("settings");
    const [value, setValue] = useState("");
    return (
        <div className="inline-flex items-center gap-1 h-6">
            <Input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => {
                    if (e.key === "Enter" && value.trim()) {
                        onAdd(value);
                        setValue("");
                    }
                }}
                placeholder={t("draftProductAdder.placeholder")}
                className="h-6 text-[11px] w-[120px] px-2 py-0"
            />
        </div>
    );
}
