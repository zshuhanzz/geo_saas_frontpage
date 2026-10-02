import { useEffect, useRef } from "react";

export function CursorGlow() {
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const el = ref.current;
        if (!el) return;

        let animId: number;
        const onMove = (e: MouseEvent) => {
            cancelAnimationFrame(animId);
            animId = requestAnimationFrame(() => {
                el.style.left = `${e.clientX}px`;
                el.style.top = `${e.clientY}px`;
                el.style.opacity = "1";
            });
        };

        const onLeave = () => {
            el.style.opacity = "0";
        };

        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseleave", onLeave);
        return () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseleave", onLeave);
            cancelAnimationFrame(animId);
        };
    }, []);

    return (
        <div
            ref={ref}
            className="fixed w-[400px] h-[400px] rounded-full pointer-events-none z-[1] -translate-x-1/2 -translate-y-1/2 opacity-0 transition-opacity duration-300 will-change-[left,top]"
            style={{
                background: "radial-gradient(circle, rgba(0,230,118,0.035) 0%, transparent 70%)",
            }}
        />
    );
}
