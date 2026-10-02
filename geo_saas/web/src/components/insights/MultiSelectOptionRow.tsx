import { Checkbox } from "@/components/ui/checkbox";

export default function MultiSelectOptionRow({
  checked,
  label,
  onlyLabel,
  onToggle,
  onOnly,
}: {
  checked: boolean;
  label: string;
  onlyLabel: string;
  onToggle: () => void;
  onOnly: () => void;
}) {
  return (
    <div className="group flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors">
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onToggle();
          }
        }}
        className="flex min-w-0 flex-1 items-center gap-2 text-left cursor-pointer"
      >
        <Checkbox checked={checked} className="pointer-events-none" />
        <span className="truncate">{label}</span>
      </div>
      <button
        type="button"
        onClick={onOnly}
        className="ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold text-primary opacity-0 transition-opacity hover:bg-primary/10 focus:opacity-100 focus:outline-none focus:ring-1 focus:ring-primary group-hover:opacity-100"
      >
        {onlyLabel}
      </button>
    </div>
  );
}
