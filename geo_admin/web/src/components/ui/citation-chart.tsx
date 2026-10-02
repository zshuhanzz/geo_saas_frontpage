import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts"

interface PieDatum {
    name: string;
    value: number;
}

const data: PieDatum[] = [
    { name: "en.wikipedia.org", value: 5.9 },
    { name: "theverge.com", value: 5.0 },
    { name: "homesandgardens.com", value: 3.5 },
    { name: "tomsguide.com", value: 3.5 },
    { name: "rtings.com", value: 3.0 },
]

const COLORS = ['#2EE89E', '#6366f1', '#8b5cf6', '#ec4899', '#f59e0b']

interface TooltipPayloadEntry {
    name?: string | number;
    value?: string | number;
    payload?: { fill?: string };
}

interface ChartTooltipProps {
    active?: boolean;
    payload?: TooltipPayloadEntry[];
}

function ChartTooltip({ active, payload }: ChartTooltipProps) {
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
            {payload.map((entry, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 6, height: 6, borderRadius: 3, background: entry.payload?.fill, boxShadow: `0 0 6px ${entry.payload?.fill}44` }} />
                    <span style={{ color: isDark ? "#e4e4e7" : "#111827", fontSize: 12, fontWeight: 600 }}>{entry.name}: {entry.value}%</span>
                </div>
            ))}
        </div>
    );
}

export function CitationChart() {
    return (
        <ResponsiveContainer width="100%" height={300}>
            <PieChart>
                <defs>
                    {COLORS.map((color, i) => (
                        <radialGradient key={i} id={`cite-pie-${i}`} cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stopColor={color} stopOpacity={1} />
                            <stop offset="100%" stopColor={color} stopOpacity={0.7} />
                        </radialGradient>
                    ))}
                </defs>
                <Pie
                    data={data}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={3}
                    dataKey="value"
                    animationDuration={800}
                    animationEasing="ease-out"
                >
                    {data.map((entry, index) => (
                        <Cell
                            key={`cell-${index}`}
                            fill={COLORS[index % COLORS.length]}
                            stroke="none"
                            style={{ filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.15))", cursor: "pointer" }}
                        />
                    ))}
                </Pie>
                <Tooltip content={<ChartTooltip />} />
                <Legend
                    wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                    iconSize={8}
                />
            </PieChart>
        </ResponsiveContainer>
    )
}
