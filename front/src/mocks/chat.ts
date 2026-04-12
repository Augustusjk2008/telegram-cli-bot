import { ChatMessage } from "../services/types";

export const mockChatMessages: Record<string, ChatMessage[]> = {
  main: [
    {
      id: "1",
      role: "assistant",
      text: "你好，我是 Kimi。有什么可以帮你的？",
      createdAt: new Date().toISOString(),
      state: "done"
    }
  ],
  team2: [
    {
      id: "2",
      role: "assistant",
      text: "Hello, I am Claude. How can I help you today?",
      createdAt: new Date().toISOString(),
      state: "done"
    }
  ]
};
