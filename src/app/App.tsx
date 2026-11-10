import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { RecordingDetail } from "@/features/recordings/RecordingDetail";
import { ConversationWorkspace } from "@/features/conversation/ConversationWorkspace";
import { ProductCatalog } from "@/features/products/ProductCatalog";
import { useRecordingLibrary } from "@/hooks/useRecordingLibrary";
import { deleteConversation, listConversations } from "@/lib/api";
import type { ConversationListItem } from "@/lib/types";
import type { LanguageChoice } from "@/lib/types";

export function App() {
  const library = useRecordingLibrary();
  const [isLight, setIsLight] = useState(false);
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  const [showConversation, setShowConversation] = useState(true);
  const [conversationKey, setConversationKey] = useState(0);
  const [conversations, setConversations] = useState<ConversationListItem[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<"recordings" | "products">("recordings");

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations());
      setConversationError(null);
    } catch (reason) {
      setConversationError(
        reason instanceof Error ? reason.message : "Could not load conversation history.",
      );
    }
  }, []);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  return (
    <AppShell
      activeSection={activeSection}
      conversations={conversations}
      error={conversationError ?? library.error}
      isLight={isLight}
      onDelete={library.remove}
      onDeleteConversation={async (id) => {
        try {
          await deleteConversation(id);
          if (selectedConversationId === id) {
            setSelectedConversationId(null);
            setConversationKey((current) => current + 1);
          }
          await refreshConversations();
        } catch (reason) {
          setConversationError(
            reason instanceof Error ? reason.message : "Could not delete the conversation.",
          );
        }
      }}
      onDismissError={() => {
        setConversationError(null);
        library.clearError();
      }}
      onNewConversation={() => {
        setActiveSection("recordings");
        library.setSelectedId(null);
        setSelectedConversationId(null);
        setShowConversation(true);
        setConversationKey((current) => current + 1);
      }}
      onNavigate={(section) => {
        setActiveSection(section);
        if (section === "recordings") {
          library.setSelectedId(null);
          setSelectedConversationId(null);
          setShowConversation(true);
          setConversationKey((current) => current + 1);
        }
      }}
      onRename={library.rename}
      onSelect={(id) => {
        setSelectedConversationId(null);
        library.setSelectedId(id);
        setShowConversation(false);
      }}
      onSelectConversation={(id) => {
        if (selectedConversationId === id && showConversation) return;
        setActiveSection("recordings");
        library.setSelectedId(null);
        setSelectedConversationId(id);
        setShowConversation(true);
        setConversationKey((current) => current + 1);
      }}
      onToggleTheme={() => setIsLight((current) => !current)}
      recordings={library.recordings}
      selectedId={library.selectedId}
      selectedConversationId={selectedConversationId}
    >
      {activeSection === "products" ? (
        <ProductCatalog />
      ) : showConversation ? (
        <ConversationWorkspace
          key={conversationKey}
          conversationId={selectedConversationId}
          onConversationCreated={(id) => {
            setSelectedConversationId(id);
            void refreshConversations();
          }}
          onConversationUpdated={() => void refreshConversations()}
        />
      ) : library.selectedRecording ? (
        <RecordingDetail
          activeAIJob={library.activeAIJob}
          activeJob={library.activeJob}
          aiModelStatus={library.aiModelStatus}
          language={language}
          onLanguageChange={setLanguage}
          onRunAI={library.runAI}
          onTranscribe={library.transcribe}
          recording={library.selectedRecording}
        />
      ) : (
        <ConversationWorkspace
          key={conversationKey}
          conversationId={selectedConversationId}
          onConversationCreated={(id) => {
            setSelectedConversationId(id);
            void refreshConversations();
          }}
          onConversationUpdated={() => void refreshConversations()}
        />
      )}
    </AppShell>
  );
}
