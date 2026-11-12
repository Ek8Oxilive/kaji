import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { ToastProvider } from "./components/Toast";
import { initLang, useLang } from "./lib/i18n";
import { ThemeProvider } from "./lib/theme";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 4000 } } });

/** Remonte l'application quand la langue change : tous les textes sont relus avec la nouvelle langue (l'adresse et le cache des données restent). */
function Root() {
  const lang = useLang();
  return <App key={lang} />;
}

// La langue (et son dictionnaire) est connue avant le premier rendu : pas de flash de français pour un lecteur anglais.
void initLang().then(() => createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <Root />
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
));
