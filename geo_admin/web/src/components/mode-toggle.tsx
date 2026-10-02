import { Moon, Sun } from "lucide-react";
import { useTheme } from "./theme-provider";

export function ModeToggle() {
    const { theme, setTheme } = useTheme();

    return (
        <button
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            className="p-2 rounded-md hover:bg-dark-800 transition-colors relative"
            aria-label="Toggle theme"
        >
            <Sun className="h-5 w-5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0 text-dark-400 hover:text-white" />
            <Moon className="absolute top-2 left-2 h-5 w-5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100 text-dark-400 hover:text-white" />
        </button>
    );
}
