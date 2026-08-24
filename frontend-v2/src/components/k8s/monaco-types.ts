/**
 * Prop types for the lazily-loaded Monaco wrapper.
 *
 * Split into its own module so importing the *types* does not drag Monaco's
 * 3.8 MB of runtime into whatever chunk the importer lands in. A plain
 * `import type { EditorProps } from '@monaco-editor/react'` is erased at
 * compile time, but the shape below is small enough to state outright and
 * keeps the dependency surface honest: this is the whole API bnkscope uses.
 */

export interface MonacoEditorProps {
  value: string;
  onChange?: (value: string | undefined) => void;
  height?: string;
  defaultLanguage?: string;
  theme?: string;
  options?: {
    readOnly?: boolean;
    minimap?: { enabled: boolean };
    scrollBeyondLastLine?: boolean;
    fontSize?: number;
    lineNumbers?: 'on' | 'off';
    folding?: boolean;
    wordWrap?: 'on' | 'off';
    automaticLayout?: boolean;
    tabSize?: number;
    renderWhitespace?: 'none' | 'selection' | 'all';
    bracketPairColorization?: { enabled: boolean };
  };
}
