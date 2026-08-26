'use client';

import { useState, useRef, useEffect } from 'react';
import { useChatStore } from '@/stores/chat-store';
import { useLanguageStore } from '@/stores/language-store';
import { useVoice } from '@/lib/hooks/use-voice';
import { Paperclip, Mic, Send, X, FileText } from 'lucide-react';

export function MessageComposer() {
  const [inputText, setInputText] = useState('');
  const textareaRef = useRef(null);

  const { sendMessage, isGenerating, attachedFile, clearAttachedFile } = useChatStore();
  const { currentLanguage, getTranslation } = useLanguageStore();
  const t = getTranslation();

  const { isListening, toggleListening, error: voiceError } = useVoice();

  // Auto resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [inputText]);

  const handleSend = () => {
    if (!inputText.trim() || isGenerating) return;
    sendMessage(inputText.trim(), currentLanguage);
    setInputText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = '44px';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleVoiceResult = (spokenText, voiceOpts) => {
    if (spokenText) {
      setInputText(spokenText);
      sendMessage(spokenText, currentLanguage, voiceOpts || { input_mode: 'voice' });
      setInputText('');
    }
  };

  return (
    <div className="absolute bottom-16 md:bottom-0 left-0 right-0 p-3 md:p-5 bg-gradient-to-t from-surface via-surface/95 to-transparent z-30 pb-safe md:pb-6">
      <div className="max-w-[840px] mx-auto relative">
        
        {/* Attached file chip */}
        {attachedFile && (
          <div className="flex items-center gap-2 mb-2 p-2 bg-surface-container-lowest rounded-xl border border-secondary shadow-sm max-w-sm">
            <FileText className="w-4 h-4 text-secondary shrink-0" />
            <span className="text-xs font-medium text-primary truncate flex-1">{attachedFile.name}</span>
            <button
              type="button"
              onClick={clearAttachedFile}
              aria-label="Remove attached file"
              className="text-on-surface-variant hover:text-error p-0.5 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Pill-shaped Composer Container */}
        <div className="bg-surface-container-high rounded-[32px] p-1.5 md:p-2 flex items-center gap-1.5 md:gap-2 shadow-ambient border border-surface-variant focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20 transition-all bg-opacity-95 backdrop-blur-sm">
          
          {/* File attachment — disabled until upload API is wired */}
          <button
            type="button"
            disabled
            title="Document attachment is not available yet"
            className="p-2.5 md:p-3 text-on-surface-variant rounded-full shrink-0 opacity-40 cursor-not-allowed"
            aria-label="Attach document (not available yet)"
            aria-disabled="true"
          >
            <Paperclip className="w-5 h-5" />
          </button>

          {/* Text input area */}
          <textarea
            ref={textareaRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isListening ? t.listening : t.askPlaceholder}
            aria-label={t.askPlaceholder}
            rows={1}
            className="flex-1 bg-transparent border-none focus:ring-0 resize-none font-sans text-sm md:text-base text-on-surface placeholder:text-outline-variant py-2.5 px-2 custom-scrollbar outline-none leading-normal"
            style={{ minHeight: '44px', maxHeight: '120px' }}
          />

          {/* Actions */}
          <div className="flex items-center gap-1 shrink-0">
            {/* Voice Mic Button */}
            <button
              type="button"
              onClick={() => toggleListening(handleVoiceResult)}
              title="Speak in Indian Languages"
              className={`p-2.5 md:p-3 rounded-full transition-all active:scale-95 relative ${
                isListening
                  ? 'bg-error-container text-on-error-container animate-pulse ring-2 ring-error'
                  : 'text-on-surface-variant hover:text-primary hover:bg-surface-variant'
              }`}
              aria-label="Voice Input"
              aria-pressed={isListening}
            >
              <Mic className="w-5 h-5" />
            </button>

            {/* Send Button */}
            <button
              type="button"
              onClick={handleSend}
              disabled={!inputText.trim() || isGenerating}
              title="Send Message"
              className="p-2.5 md:p-3 bg-primary text-on-primary rounded-full hover:bg-surface-tint transition-all active:scale-90 flex items-center justify-center shadow-ambient disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Send Message"
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>

        {voiceError && (
          <p className="text-center mt-2 text-xs text-error font-medium" role="alert">
            {voiceError}
          </p>
        )}

        {/* Disclaimer */}
        <div className="text-center mt-1.5">
          <p className="text-[10px] text-outline">
            {t.disclaimer}
          </p>
        </div>

      </div>
    </div>
  );
}
