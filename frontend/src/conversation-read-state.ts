import type { ConversationSummary } from "@/types";

const KEY_PREFIX = "jobiss:conversation-seen:";

export function markConversationSeen(conversationId: string, lastMessageAt: string) {
  if (!lastMessageAt) return;
  window.localStorage.setItem(`${KEY_PREFIX}${conversationId}`, lastMessageAt);
}

export function hasUnreadCompletedReply(item: ConversationSummary) {
  if (
    item.aiReplyPending ||
    item.latestJobFailed ||
    item.latestMessageRole !== "ASSISTANT" ||
    !item.lastMessageAt
  ) {
    return false;
  }
  const seenAt = window.localStorage.getItem(`${KEY_PREFIX}${item.id}`);
  return !seenAt || Date.parse(item.lastMessageAt) > Date.parse(seenAt);
}
