import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChevronDown, Search, Check, X } from "lucide-react";

/* ====================== Searchable Multi-Select Combobox ====================== */
export function SearchableMultiSelect({
    label,
    icon,
    options,
    selected,
    onChange,
    getOptionLabel,
    getOptionValue,
    placeholder,
}: {
    label: string;
    icon: React.ReactNode;
    options: any[];
    selected: string[];
    onChange: (val: string[]) => void;
    getOptionLabel: (opt: any) => string;
    getOptionValue: (opt: any) => string;
    placeholder?: string;
}) {
    const { t } = useTranslation("insights");
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState("");
    const inputRef = useRef<HTMLInputElement>(null);

    const resolvedPlaceholder = placeholder ?? t("promptEditor.multiSelect.placeholder");

    const filtered = options.filter(opt =>
        getOptionLabel(opt).toLowerCase().includes(search.toLowerCase())
    );

    const toggleOption = (val: string) => {
        onChange(selected.includes(val) ? selected.filter(v => v !== val) : [...selected, val]);
    };

    const displayText = selected.length === 0
        ? resolvedPlaceholder
        : selected.length === 1
            ? options.find(o => getOptionValue(o) === selected[0]) ? getOptionLabel(options.find(o => getOptionValue(o) === selected[0])!) : selected[0]
            : t("promptEditor.multiSelect.nSelected", { count: selected.length });

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <button
                    className="w-full flex items-center gap-2 h-10 px-3 rounded-md border border-input bg-background text-sm hover:bg-accent/50 transition-colors"
                    onClick={() => { setOpen(!open); setSearch(""); }}
                >
                    <span className="text-muted-foreground shrink-0">{icon}</span>
                    <span className={`flex-1 text-left truncate ${selected.length === 0 ? 'text-muted-foreground' : ''}`}>
                        {displayText}
                    </span>
                    {selected.length > 0 && (
                        <span
                            className="text-muted-foreground hover:text-foreground"
                            onClick={(e) => { e.stopPropagation(); onChange([]); }}
                        >
                            <X className="h-3.5 w-3.5" />
                        </span>
                    )}
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                </button>
            </PopoverTrigger>
            <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
                <div className="p-2 border-b">
                    <div className="flex items-center gap-2 px-2">
                        <Search className="h-4 w-4 text-muted-foreground shrink-0" />
                        <input
                            ref={inputRef}
                            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                            placeholder={t("promptEditor.multiSelect.searchLabel", { label: label.toLowerCase() })}
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            autoFocus
                        />
                    </div>
                </div>
                <div className="max-h-[200px] overflow-y-auto py-1">
                    {filtered.length === 0 && (
                        <div className="px-4 py-3 text-sm text-muted-foreground text-center">{t("promptEditor.multiSelect.noResults")}</div>
                    )}
                    {filtered.map(opt => {
                        const val = getOptionValue(opt);
                        const isSelected = selected.includes(val);
                        return (
                            <button
                                key={val}
                                className={`w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent/50 transition-colors text-left ${isSelected ? 'bg-accent/30' : ''}`}
                                onClick={() => toggleOption(val)}
                            >
                                <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${isSelected ? 'bg-primary border-primary' : 'border-input'}`}>
                                    {isSelected && <Check className="h-3 w-3 text-primary-foreground" />}
                                </div>
                                <span className="truncate">{getOptionLabel(opt)}</span>
                            </button>
                        );
                    })}
                </div>
            </PopoverContent>
        </Popover>
    );
}
