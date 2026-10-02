import { createContext, useContext, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

const ConfirmContext = createContext<
  ((message: string, title?: string) => Promise<boolean>) | null
>(null);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation("common");
  const [state, setState] = useState<{
    open: boolean;
    title: string;
    message: string;
    resolve: ((v: boolean) => void) | null;
  }>({ open: false, title: "", message: "", resolve: null });

  const confirm = useCallback(
    (message: string, title?: string) => {
      return new Promise<boolean>((resolve) => {
        setState({
          open: true,
          title: title ?? t("confirmDialog.defaultTitle"),
          message,
          resolve,
        });
      });
    },
    [t],
  );

  const handleResult = (result: boolean) => {
    state.resolve?.(result);
    setState({ open: false, title: "", message: "", resolve: null });
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog
        open={state.open}
        onOpenChange={(open) => {
          if (!open) handleResult(false);
        }}
      >
        <DialogContent hideCloseButton>
          <DialogHeader>
            <DialogTitle>{state.title}</DialogTitle>
            <DialogDescription>{state.message}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => handleResult(false)}>
              {t("actions.cancel")}
            </Button>
            <Button variant="destructive" onClick={() => handleResult(true)}>
              {t("actions.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
}
