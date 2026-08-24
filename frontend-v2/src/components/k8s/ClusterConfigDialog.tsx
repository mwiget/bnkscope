/**
 * ClusterConfigDialog — register or edit a cluster from a kubeconfig.
 *
 * This used to carry an SSH tunnel section and a "probe the remote host over
 * SSH" flow. Both went with the SSH subsystem in bnkscope Phase 3, so what is
 * left is the kubeconfig itself plus the handful of fields that describe the
 * cluster. Phase 5 replaces even this with autodiscovery over the local
 * kubeconfig's contexts; until then, upload one.
 */

import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useCreateCluster, useUpdateCluster } from '@/hooks/useK8s';
import type { K8sCluster, K8sClusterCreateRequest, K8sClusterUpdateRequest } from '@/types';
import { Loader2, Upload, FileText } from 'lucide-react';
import { SectionCard } from '@/components/ui/section-card';
import { notify } from '@/lib/notify';

interface ClusterConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  cluster?: K8sCluster | null;
}

const EMPTY_FORM = {
  name: '',
  kubeconfig: '',
  cloud_provider: '',
  region: '',
  context: '',
  default_namespace: 'default',
};

export function ClusterConfigDialog({ open, onOpenChange, cluster }: ClusterConfigDialogProps) {
  // silent=true: all error display is owned here so the KUBECONFIG_UNPORTABLE
  // case can render inline on the field rather than as a toast.
  const createMutation = useCreateCluster({ silent: true });
  const updateMutation = useUpdateCluster({ silent: true });
  const isEditing = !!cluster;

  const [formData, setFormData] = useState({ ...EMPTY_FORM });
  const [kubeconfigFile, setKubeconfigFile] = useState<string | null>(null);
  const [kubeconfigError, setKubeconfigError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setKubeconfigError(null);
    setKubeconfigFile(null);
    if (cluster) {
      setFormData({
        name: cluster.name,
        kubeconfig: '',
        cloud_provider: cluster.cloud_provider || '',
        region: cluster.region || '',
        context: cluster.context || '',
        default_namespace: cluster.default_namespace || 'default',
      });
    } else {
      setFormData({ ...EMPTY_FORM });
    }
  }, [cluster, open]);

  const handleFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? '');
      setFormData((prev) => ({ ...prev, kubeconfig: btoa(text) }));
      setKubeconfigFile(file.name);
      setKubeconfigError(null);
    };
    reader.readAsText(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!isEditing && !formData.kubeconfig) {
      notify.error('Please upload a kubeconfig file', undefined, { category: 'credentials' });
      return;
    }

    // KUBECONFIG_UNPORTABLE → inline field message; everything else → toast.
    const handleMutationError = (err: unknown) => {
      const axiosErr = err as {
        response?: { data?: { error?: { code?: string; details?: { user_message?: string } } } };
      };
      const apiError = axiosErr?.response?.data?.error;
      if (apiError?.code === 'KUBECONFIG_UNPORTABLE') {
        setKubeconfigError(
          apiError.details?.user_message ??
            'Kubeconfig is not portable. Please upload a flattened kubeconfig.',
        );
      } else {
        notify.error('Failed to save cluster configuration', undefined, { category: 'credentials' });
      }
    };

    try {
      if (isEditing && cluster) {
        const updateData: K8sClusterUpdateRequest = {
          name: formData.name !== cluster.name ? formData.name : undefined,
          cloud_provider: formData.cloud_provider || undefined,
          region: formData.region || undefined,
          context: formData.context || undefined,
          default_namespace: formData.default_namespace || undefined,
        };
        if (formData.kubeconfig) {
          updateData.kubeconfig = formData.kubeconfig;
        }
        await updateMutation.mutateAsync(
          { clusterId: cluster.id, data: updateData },
          { onError: handleMutationError },
        );
      } else {
        const createData: K8sClusterCreateRequest = {
          name: formData.name,
          kubeconfig: formData.kubeconfig,
          cloud_provider: formData.cloud_provider || undefined,
          region: formData.region || undefined,
          context: formData.context || undefined,
          default_namespace: formData.default_namespace || undefined,
        };
        await createMutation.mutateAsync({ data: createData }, { onError: handleMutationError });
      }
      onOpenChange(false);
    } catch {
      // Already surfaced by handleMutationError.
    }
  };

  const handleChange = (field: string, value: string) =>
    setFormData((prev) => ({ ...prev, [field]: value }));

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEditing ? 'Edit Cluster' : 'Add Cluster'}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? 'Update this cluster. Upload a new kubeconfig only if it has changed.'
              : 'Register a Kubernetes cluster by uploading its kubeconfig.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <SectionCard title="Cluster Identity" compact>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => handleChange('name', e.target.value)}
                  placeholder="prod-cluster"
                  required
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="kubeconfig">
                  Kubeconfig{isEditing ? ' (leave empty to keep the current one)' : ''}
                </Label>
                <div className="flex items-center gap-2">
                  <Button type="button" variant="outline" size="sm" asChild>
                    <label className="cursor-pointer">
                      <Upload className="h-3.5 w-3.5 mr-1.5" />
                      Choose file
                      <input
                        id="kubeconfig"
                        type="file"
                        className="hidden"
                        accept=".yaml,.yml,.conf,.config,text/*"
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) handleFile(f);
                        }}
                      />
                    </label>
                  </Button>
                  {kubeconfigFile && (
                    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <FileText className="h-3.5 w-3.5" />
                      {kubeconfigFile}
                    </span>
                  )}
                </div>
                {kubeconfigError && <p className="text-xs text-destructive">{kubeconfigError}</p>}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="context">Context (optional — defaults to current-context)</Label>
                <Input
                  id="context"
                  value={formData.context}
                  onChange={(e) => handleChange('context', e.target.value)}
                  placeholder="kubernetes-admin@prod"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="cloud_provider">Provider</Label>
                  <Select
                    value={formData.cloud_provider}
                    onValueChange={(v) => handleChange('cloud_provider', v)}
                  >
                    <SelectTrigger id="cloud_provider">
                      <SelectValue placeholder="on-prem" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="on-prem">on-prem</SelectItem>
                      <SelectItem value="aws">aws / eks</SelectItem>
                      <SelectItem value="gcp">gcp / gke</SelectItem>
                      <SelectItem value="azure">azure / aks</SelectItem>
                      <SelectItem value="ibm">ibm / roks</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="region">Region</Label>
                  <Input
                    id="region"
                    value={formData.region}
                    onChange={(e) => handleChange('region', e.target.value)}
                    placeholder="us-east-1"
                  />
                </div>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="default_namespace">Default namespace</Label>
                <Input
                  id="default_namespace"
                  value={formData.default_namespace}
                  onChange={(e) => handleChange('default_namespace', e.target.value)}
                  placeholder="default"
                />
              </div>
            </div>
          </SectionCard>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {isEditing ? 'Save' : 'Add Cluster'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
