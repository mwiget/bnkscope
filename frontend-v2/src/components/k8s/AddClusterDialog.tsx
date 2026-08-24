/**
 * Adding a cluster, both ways.
 *
 * Discovery is the primary path — bnkscope is running on the machine that
 * already talks to these clusters, so the answer is usually already in
 * ~/.kube/config. The kubeconfig form is the fallback for the cases discovery
 * cannot cover: a cluster you have credentials for but no local context, or one
 * whose context uses an auth plugin bnkscope cannot run.
 *
 * Both live in one dialog because they answer the same question, and putting
 * the paste-a-kubeconfig form first would suggest typing is the normal route.
 */
import { useState } from 'react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ClusterConfigDialog } from './ClusterConfigDialog';
import { ClusterDiscoveryPanel } from './ClusterDiscoveryPanel';

interface AddClusterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddClusterDialog({ open, onOpenChange }: AddClusterDialogProps) {
  const [showManualForm, setShowManualForm] = useState(false);

  return (
    <>
      <Dialog open={open && !showManualForm} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Add a cluster</DialogTitle>
            <DialogDescription>
              Clusters running BNK are picked up from your kubeconfig automatically. Anything
              else can be added from the list below.
            </DialogDescription>
          </DialogHeader>

          <ClusterDiscoveryPanel className="border-0 p-0" />

          <div className="mt-2 border-t border-border pt-4">
            <p className="text-sm text-muted-foreground">
              Not in your kubeconfig, or using an auth plugin bnkscope cannot run?
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => setShowManualForm(true)}
            >
              Paste a kubeconfig instead
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <ClusterConfigDialog
        open={showManualForm}
        onOpenChange={(next) => {
          setShowManualForm(next);
          // Closing the form closes the whole flow — the user is done either
          // way, and dropping them back on the candidate list reads as a
          // failure when the add actually succeeded.
          if (!next) onOpenChange(false);
        }}
      />
    </>
  );
}
