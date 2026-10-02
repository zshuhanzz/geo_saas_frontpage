import { useMemo, useState } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export interface SearchableEntityOption {
    value: string;
    label: string;
    description?: string | null;
    avatarUrl?: string | null;
}

interface SearchableEntitySelectProps {
    value: string;
    options: SearchableEntityOption[];
    onChange: (value: string) => void;
    placeholder: string;
    searchPlaceholder?: string;
    disabled?: boolean;
}

export function SearchableEntitySelect({
    value,
    options,
    onChange,
    placeholder,
    searchPlaceholder = "Search...",
    disabled = false,
}: SearchableEntitySelectProps) {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState("");
    const selected = options.find((option) => option.value === value);
    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return options;
        return options.filter((option) => {
            return (
                option.label.toLowerCase().includes(q) ||
                (option.description || "").toLowerCase().includes(q)
            );
        });
    }, [options, search]);

    return (
        <div className="relative">
            <Button
                type="button"
                variant="outline"
                disabled={disabled}
                className="h-10 w-full justify-between px-3 font-normal"
                onClick={() => setOpen((next) => !next)}
            >
                <span className="min-w-0 truncate text-left">
                    {selected ? selected.label : placeholder}
                </span>
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
            </Button>

            {open && (
                <Card className="absolute z-50 mt-2 w-full overflow-hidden border shadow-xl">
                    <div className="border-b p-2">
                        <div className="relative">
                            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                            <Input
                                autoFocus
                                value={search}
                                onChange={(event) => setSearch(event.target.value)}
                                placeholder={searchPlaceholder}
                                className="h-8 pl-8 pr-8 text-sm"
                            />
                            {search && (
                                <button
                                    type="button"
                                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                    onClick={() => setSearch("")}
                                >
                                    <X className="h-3.5 w-3.5" />
                                </button>
                            )}
                        </div>
                    </div>
                    <div className="max-h-64 overflow-y-auto p-1">
                        {filtered.length === 0 && (
                            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                                No matches found
                            </div>
                        )}
                        {filtered.map((option) => {
                            const active = option.value === value;
                            return (
                                <button
                                    key={option.value}
                                    type="button"
                                    className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent/60 ${active ? "bg-primary/10" : ""}`}
                                    onClick={() => {
                                        onChange(option.value);
                                        setOpen(false);
                                        setSearch("");
                                    }}
                                >
                                    <div className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xs font-semibold">
                                        {option.avatarUrl ? (
                                            <img src={option.avatarUrl} alt="" className="h-full w-full object-cover" />
                                        ) : (
                                            option.label.slice(0, 1).toUpperCase()
                                        )}
                                    </div>
                                    <div className="min-w-0 flex-1">
                                        <div className="truncate font-medium text-foreground">{option.label}</div>
                                        {option.description && (
                                            <div className="truncate text-xs text-muted-foreground">{option.description}</div>
                                        )}
                                    </div>
                                    {active && <Check className="h-4 w-4 text-primary" />}
                                </button>
                            );
                        })}
                    </div>
                </Card>
            )}
        </div>
    );
}
