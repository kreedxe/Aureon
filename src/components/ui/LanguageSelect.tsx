import { ChevronDown, Languages } from "lucide-react";
import type { LanguageChoice } from "@/lib/types";

const languages: { value: LanguageChoice; label: string }[] = [
  { value: "auto", label: "Auto detect" },
  { value: "uz", label: "Uzbek" },
  { value: "ru", label: "Russian" },
  { value: "en", label: "English" },
];

interface LanguageSelectProps {
  value: LanguageChoice;
  onChange: (value: LanguageChoice) => void;
  disabled?: boolean;
}

export function LanguageSelect({ value, onChange, disabled }: LanguageSelectProps) {
  return (
    <label className={`language-select${disabled ? " disabled" : ""}`}>
      <Languages aria-hidden="true" size={15} />
      <select
        aria-label="Transcription language"
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as LanguageChoice)}
        value={value}
      >
        {languages.map((language) => (
          <option key={language.value} value={language.value}>{language.label}</option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" className="select-chevron" size={13} />
    </label>
  );
}
