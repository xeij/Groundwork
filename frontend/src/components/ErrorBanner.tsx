import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";

interface Props {
  message: string;
  onDismiss?: () => void;
}

export function ErrorBanner({ message, onDismiss }: Props) {
  return (
    <Alert variant="destructive" className="flex items-start justify-between gap-3">
      <AlertDescription>{message}</AlertDescription>
      {onDismiss && (
        <Button variant="ghost" size="sm" onClick={onDismiss} className="h-auto shrink-0 px-2 py-0.5 text-current hover:bg-destructive/15">
          Dismiss
        </Button>
      )}
    </Alert>
  );
}
