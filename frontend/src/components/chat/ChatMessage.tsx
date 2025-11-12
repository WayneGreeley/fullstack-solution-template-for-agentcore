import { Message } from "./types"

interface ChatMessageProps {
  message: Message
}

export function ChatMessage({ message }: ChatMessageProps) {
  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div
      className={`flex flex-col ${message.role === "user" ? "items-end" : "items-start"}`}
    >
      <div
        className={`max-w-[80%] p-3 rounded-lg whitespace-pre-wrap break-words ${
          message.role === "user"
            ? "bg-gray-800 text-white rounded-br-none"
            : "bg-gray-100 text-gray-800 rounded-bl-none"
        }`}
      >
        {message.content}
      </div>
      <div className="text-xs text-gray-500 mt-1 px-1">
        {formatTime(message.timestamp)}
      </div>
    </div>
  )
}