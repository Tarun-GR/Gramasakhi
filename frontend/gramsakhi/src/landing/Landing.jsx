import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Sprout,
  Mic,
  BookOpen,
  Shield,
  CheckCircle2,
  Globe,
  MessageSquarePlus,
} from "lucide-react";
import { MarketingPage } from "../gramasakhi-ui/components/marketing/MarketingShell";
import { GsButton } from "../gramasakhi-ui/components/marketing/GsButton";
import "../gramasakhi-ui/globals.css";

const features = [
  {
    icon: Mic,
    title: "Voice-first access",
    desc: "Ask about schemes by speaking — designed for users with limited digital literacy.",
  },
  {
    icon: BookOpen,
    title: "Grounded answers",
    desc: "Responses come from verified government documents — not free-form guessing.",
  },
  {
    icon: Globe,
    title: "Multilingual",
    desc: "Kannada, Hindi, and English support with responses grounded in official sources.",
  },
  {
    icon: Shield,
    title: "Evidence-first",
    desc: "If reliable evidence is missing, GramSakhi says so instead of inventing rules.",
  },
];

export default function Landing() {
  const navigate = useNavigate();

  const navRight = (
    <>
      <GsButton variant="ghost" size="sm" onClick={() => navigate("/admin/login")}>
        Admin
      </GsButton>
      <GsButton size="sm" onClick={() => navigate("/citizen/login")}>
        Sign in
      </GsButton>
    </>
  );

  return (
    <MarketingPage navRight={navRight}>
      <section className="relative pt-28 pb-16 md:pb-24 min-h-[88vh] flex items-center overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-surface-container-low via-background to-secondary-container/30" />
        <div className="absolute -right-16 top-20 w-72 h-72 md:w-[28rem] md:h-[28rem] rounded-full bg-secondary/15 blur-3xl pointer-events-none" />

        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 w-full">
          <div className="max-w-3xl">
            <div className="w-20 h-20 bg-surface-container-high rounded-full flex items-center justify-center shadow-ambient border border-surface-variant/50 relative mb-8">
              <Sprout className="w-10 h-10 text-primary" />
              <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-secondary-container flex items-center justify-center shadow-sm">
                <CheckCircle2 className="w-4 h-4 text-secondary" />
              </div>
            </div>

            <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-secondary mb-3">
              Last-mile governance
            </p>
            <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold text-primary tracking-tight leading-[1.08]">
              Your trusted advisor for government schemes
            </h1>
            <p className="mt-5 text-base sm:text-lg text-on-surface-variant max-w-xl leading-relaxed">
              A vernacular, voice-first assistant for reliable scheme information — grounded in
              verified official documents.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <GsButton size="lg" onClick={() => navigate("/citizen/login")}>
                <MessageSquarePlus className="w-5 h-5" />
                Get started
              </GsButton>
              <GsButton variant="secondary" size="lg" onClick={() => navigate("/citizen/login")}>
                <Mic className="w-5 h-5" />
                Ask by voice
              </GsButton>
            </div>
          </div>
        </div>
      </section>

      <section className="py-16 md:py-20 bg-surface-container-low border-y border-surface-variant/60">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <h2 className="text-2xl md:text-3xl font-bold text-primary mb-2">Built for citizens first</h2>
          <p className="text-on-surface-variant mb-10 max-w-2xl text-sm md:text-base">
            Accuracy, grounding, accessibility, and vernacular support — not a general chatbot.
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
            {features.map((f) => (
              <div
                key={f.title}
                className="p-5 rounded-2xl border border-surface-variant bg-surface-container-lowest shadow-ambient hover:border-secondary/50 transition-colors"
              >
                <div className="w-10 h-10 rounded-xl bg-secondary-container flex items-center justify-center mb-3">
                  <f.icon className="w-5 h-5 text-secondary" />
                </div>
                <h3 className="font-bold text-primary text-sm md:text-base mb-1.5">{f.title}</h3>
                <p className="text-xs md:text-sm text-on-surface-variant leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="py-14 md:py-16">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 text-center">
          <p className="text-on-surface-variant text-sm mb-4">Ready to explore schemes with verified guidance?</p>
          <GsButton size="lg" onClick={() => navigate("/citizen/login")}>
            Sign in to GramSakhi
          </GsButton>
        </div>
      </section>
    </MarketingPage>
  );
}
