import { useState, useEffect } from 'react';
import { SectionCard } from '@/components/ui/section-card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Loader2, Save } from 'lucide-react';
import { useSystemDefaults } from '@/hooks/useSettings';

export default function SystemDefaults() {
  const { defaults, isLoading, updateDefaults, isUpdating } = useSystemDefaults();

  // Form state
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [hasChanges, setHasChanges] = useState(false);

  // Initialize form values from defaults
  useEffect(() => {
    if (defaults) {
      const values: Record<string, string> = {};

      // Flatten all categories into form values
      Object.values(defaults).forEach((category: Record<string, { key: string; raw_value?: string }>) => {
        Object.values(category).forEach((setting: { key: string; raw_value?: string }) => {
          values[setting.key] = setting.raw_value || '';
        });
      });

      setFormValues(values);
      setHasChanges(false);
    }
  }, [defaults]);

  const handleChange = (key: string, value: string) => {
    setFormValues(prev => ({ ...prev, [key]: value }));
    setHasChanges(true);
  };

  const handleSave = () => {
    // Only send changed values
    const updates: Record<string, string> = {};

    if (defaults) {
      Object.values(defaults).forEach((category: Record<string, { key: string; raw_value?: string }>) => {
        Object.values(category).forEach((setting: { key: string; raw_value?: string }) => {
          const newValue = formValues[setting.key];
          if (newValue !== setting.raw_value) {
            updates[setting.key] = newValue;
          }
        });
      });
    }

    if (Object.keys(updates).length > 0) {
      updateDefaults(updates);
      setHasChanges(false);
    }
  };

  const handleReset = () => {
    if (defaults) {
      const values: Record<string, string> = {};
      Object.values(defaults).forEach((category: Record<string, { key: string; raw_value?: string }>) => {
        Object.values(category).forEach((setting: { key: string; raw_value?: string }) => {
          values[setting.key] = setting.raw_value || '';
        });
      });
      setFormValues(values);
      setHasChanges(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Save Button */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-foreground">
            System Defaults
          </h3>
          <p className="text-sm text-muted-foreground">
            How bnkscope retries a failed operation. Nothing here is required to
            use it — the defaults are sensible.
          </p>
        </div>
        <div className="flex gap-2">
          {hasChanges && (
            <Button
              variant="outline"
              onClick={handleReset}
            >
              Reset
            </Button>
          )}
          <Button
            onClick={handleSave}
            disabled={isUpdating || !hasChanges}
          >
            {isUpdating ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Save className="h-4 w-4 mr-2" />
                Save Changes
              </>
            )}
          </Button>
        </div>
      </div>


      {/* Execution Settings */}
      <SectionCard title="Execution settings">
        <p className="text-sm text-muted-foreground -mt-1 mb-4">
          Retry behavior for failed operations
        </p>
        <div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Max Retries</Label>
              <Input
                type="number"
                min="0"
                max="10"
                value={formValues['execution.max_retries'] || ''}
                onChange={(e) => handleChange('execution.max_retries', e.target.value)}
                className="w-24"
              />
              <p className="text-xs text-muted-foreground">Number of retry attempts (0-10)</p>
            </div>

            <div className="space-y-2">
              <Label>Retry Delay</Label>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min="1"
                  max="60"
                  value={formValues['execution.retry_delay'] || ''}
                  onChange={(e) => handleChange('execution.retry_delay', e.target.value)}
                  className="w-24"
                />
                <span className="text-sm text-muted-foreground">sec</span>
              </div>
              <p className="text-xs text-muted-foreground">Delay between retries (1-60)</p>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
