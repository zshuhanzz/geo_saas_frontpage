import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts"

interface BarDatum {
    name: string;
    score: number;
}

const data: BarDatum[] = [
    { name: "Roborock", score: 48 },
    { name: "Eufy", score: 36 },
    { name: "iRobot", score: 32 },
    { name: "Dreame", score: 24 },
    { name: "Shark", score: 20 },
]

interface TooltipPayloadEntry {
    color?: string;
    value?: string | number;
}

interface ChartTooltipProps {
    active?: boolean;
    payload?: TooltipPayloadEntry[];
    label?: string | number;
}

function ChartTooltip({ active, payload, label }: ChartTooltipProps) {
    if (!active || !payload?.length) return null;
    const isDark = document.documentElement.classList.contains("dark");
    return (
        <div style={{
            background: isDark ? "rgba(15,15,20,0.92)" : "rgba(255,255,255,0.96)",
            border: isDark ? "1px solid rgba(46,232,158,0.2)" : "1px solid rgba(0,0,0,0.08)",
            borderRadius: 10, padding: "8px 12px",
            backdropFilter: "blur(12px)",
            boxShadow: isDark ? "0 8px 24px rgba(0,0,0,0.4)" : "0 8px 24px rgba(0,0,0,0.1)",
        }}>
            <p style={{ color: isDark ? "#a1a1aa" : "#6b7280", fontSize: 11, marginBottom: 4, fontWeight: 500 }}>{label}</p>
            {payload.map((entry, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 6, height: 6, borderRadius: 3, background: entry.color, boxShadow: `0 0 6px ${entry.color}44` }} />
                    <span style={{ color: isDark ? "#e4e4e7" : "#111827", fontSize: 12, fontWeight: 600 }}>{entry.value}%</span>
                </div>
            ))}
        </div>
    );
}

export function VisibilityChart() {
    return (
        <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data} margin={{ top: 20, right: 0, left: -20, bottom: 0 }}>
                <defs>
                    <linearGradient id="vis-bar-grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#2EE89E" stopOpacity={0.95} />
                        <stop offset="100%" stopColor="#2EE89E" stopOpacity={0.5} />
                    </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis
                    dataKey="name"
                    stroke="transparent"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "hsl(var(--muted-foreground))" }}
                />
                <YAxis
                    stroke="transparent"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "hsl(var(--muted-foreground))" }}
                    tickFormatter={(value) => `${value}%`}
                />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(46,232,158,0.04)", radius: 4 }} />
                <Bar
                    dataKey="score"
                    fill="url(#vis-bar-grad)"
                    radius={[6, 6, 0, 0]}
                    maxBarSize={40}
                    animationDuration={800}
                    animationEasing="ease-out"
                />
            </BarChart>
        </ResponsiveContainer>
    )
}
