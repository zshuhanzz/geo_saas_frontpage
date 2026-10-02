/* User message — right-aligned green bubble */
export function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-lg rounded-2xl rounded-tr-md bg-primary text-primary-foreground px-5 py-3 text-sm whitespace-pre-wrap leading-relaxed shadow-sm">
        {content}
      </div>
    </div>
  );
}
