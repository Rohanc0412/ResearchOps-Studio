export function TypingIndicator() {
  return (
    <div className="flex gap-1 py-2">
      {[0, 1, 2].map((index) => (
        <div
          key={index}
          className="h-2 w-2 animate-bounce rounded-full bg-emerald-500"
          style={{ animationDelay: `${index * 0.2}s` }}
        />
      ))}
    </div>
  );
}
