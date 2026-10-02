/**
 * Custom field barrel — side-effect imports that register every real
 * `customFieldRegistry` entry. Importing this module once (see
 * WizardShell.tsx) replaces the Round 1 stubs with the real components.
 *
 * Each module below self-registers via `registerCustomField(type, cmp)`
 * at module-init time. Add new custom fields here as they land.
 */
import "./ChartBuilder";
import "./PromptEditor";
import "./PeerPicker";
import "./AnalyzerImport";
import "./StrategyGenerator";
import "./ProductFactsForm";
import "./PromptRefPicker";
import "./TopicRefPicker";
import "./ModeGatePicker";
import "./ExecutionPreview";
import "./RedditDiscoveryConfig";
import "./OfficialWebsiteDiscoveryConfig";
import "./CitationAnalysisPreflight";
import "./SubredditTargetingPreflight";
import "./RedditDiscoveryPreflight";
import "./PromptArtifactPreparationPreflight";
