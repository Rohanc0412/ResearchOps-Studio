import { motion } from "framer-motion";

export function TypingIndicator() {
  return (
    <div className="flex gap-1 py-2" role="status" aria-label="Assistant is typing">
      <span className="sr-only">Assistant is typing</span>
      {[0, 1, 2].map((index) => (
        <motion.div
          key={index}
          className="h-2 w-2 rounded-full bg-emerald-500"
          animate={{ y: [0, -6, 0] }}
          transition={{
            duration: 0.6,
            repeat: Infinity,
            ease: "easeInOut",
            delay: index * 0.15,
          }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}
