import React from "react";
import { Landmark, Mic, BookOpen, Phone, Shield } from "lucide-react";
import { Btn } from "../components/ui/Btn";

const features = [
  {
    icon: Mic,
    title: "Voice-first access",
    desc: "Ask about schemes by speaking — designed for users with limited digital literacy.",
  },
  {
    icon: BookOpen,
    title: "Grounded answers",
    desc: "Responses come from verified government documents via RAG — not free-form guessing.",
  },
  {
    icon: Phone,
    title: "IVR / telephone",
    desc: "Reach GramSakhi over a phone call when a smartphone is not available.",
  },
  {
    icon: Shield,
    title: "Evidence-first",
    desc: "If the knowledge base lacks evidence, GramSakhi says so instead of inventing rules.",
  },
];

export default function Landing() {
  const goCitizen = () => {
    window.location.href = "http://localhost:5176/login";
  };
  const goAdmin = () => {
    window.location.href = "http://localhost:5174/login";
  };

  return (
    <div className="min-h-screen bg-[#F3F7F2] text-[#1A2E1F] font-sans">
      <nav className="fixed top-0 left-0 right-0 z-40 bg-[#F3F7F2]/90 backdrop-blur border-b border-[#D5E3D4]">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[#2F6B3A] flex items-center justify-center">
              <Landmark className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-lg tracking-tight">GramSakhi</span>
          </div>
          <div className="flex items-center gap-3">
            <Btn variant="ghost" size="sm" onClick={goAdmin}>
              Admin
            </Btn>
            <Btn size="sm" onClick={goCitizen}>
              Ask GramSakhi
            </Btn>
          </div>
        </div>
      </nav>

      <section className="relative pt-28 pb-20 min-h-[85vh] flex items-center overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-[#E4F0E2] via-[#F3F7F2] to-[#E8F2EA]" />
        <div className="absolute -right-20 top-24 w-[28rem] h-[28rem] rounded-full bg-[#2F6B3A]/10 blur-3xl" />
        <div className="relative max-w-6xl mx-auto px-6 w-full">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[#2F6B3A] mb-4">
            Last-mile governance
          </p>
          <h1 className="text-5xl sm:text-6xl md:text-7xl font-black tracking-tight max-w-3xl leading-[1.05]">
            GramSakhi
          </h1>
          <p className="mt-5 text-lg sm:text-xl text-[#3F5544] max-w-xl">
            A vernacular, voice-first assistant for reliable government scheme information —
            grounded in verified documents.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Btn size="lg" onClick={goCitizen}>
              Ask by text
            </Btn>
            <Btn variant="ghost" size="lg" onClick={goCitizen}>
              Ask by voice
            </Btn>
          </div>
        </div>
      </section>

      <section className="py-20 border-t border-[#D5E3D4] bg-white">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-3xl font-bold mb-3">Built for citizens first</h2>
          <p className="text-[#5A6B5D] mb-10 max-w-2xl">
            Accuracy, grounding, accessibility, and vernacular support — not a general chatbot.
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8">
            {features.map((f) => (
              <div key={f.title} className="space-y-3">
                <f.icon className="w-6 h-6 text-[#2F6B3A]" />
                <h3 className="font-bold text-lg">{f.title}</h3>
                <p className="text-sm text-[#5A6B5D] leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="py-8 border-t border-[#D5E3D4] text-center text-sm text-[#5A6B5D]">
        GramSakhi — RAG-based vernacular GenAI + IVR for last-mile governance
      </footer>
    </div>
  );
}
