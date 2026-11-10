import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { RecordingDetail } from "@/features/recordings/RecordingDetail";
import { ConversationWorkspace } from "@/features/conversation/ConversationWorkspace";
import { ProductCatalog } from "@/features/products/ProductCatalog";
import { useRecordingLibrary } from "@/hooks/useRecordingLibrary";
import type { LanguageChoice } from "@/lib/types";

export function App() {
  const library = useRecordingLibrary();
  const [isLight, setIsLight] = useState(false);
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  const [showConversation, setShowConversation] = useState(true);
  const [conversationKey, setConversationKey] = useState(0);
  const [activeSection, setActiveSection] = useState<"recordings" | "products">("recordings");

  return (
    <AppShell
      activeSection={activeSection}
      error={library.error}
      isLight={isLight}
      onDelete={library.remove}
      onDismissError={library.clearError}
      onNewConversation={() => {
        setActiveSection("recordings");
        library.setSelectedId(null);
        setShowConversation(true);
        setConversationKey((current) => current + 1);
      }}
      onNavigate={(section) => {
        setActiveSection(section);
        if (section === "recordings") {
          library.setSelectedId(null);
          setShowConversation(true);
        }
      }}
      onRename={library.rename}
      onSelect={(id) => {
        library.setSelectedId(id);
        setShowConversation(false);
      }}
      onToggleTheme={() => setIsLight((current) => !current)}
      recordings={library.recordings}
      selectedId={library.selectedId}
    >
      {activeSection === "products" ? (
        <ProductCatalog />
      ) : showConversation ? (
        <ConversationWorkspace key={conversationKey} />
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
        <ConversationWorkspace key={conversationKey} />
      )}
    </AppShell>
  );
}
