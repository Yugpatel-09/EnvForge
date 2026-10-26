import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Copy,
  Download,
  FlaskConical,
  GitCompare,
  Layers,
  LockKeyhole,
  Play,
  Plug,
  ShieldCheck,
  Terminal,
  XCircle,
} from "lucide-react";
import { api } from "./api";
import type {
  Agent,
  Environment,
  Episode,
  Evaluation,
  QA,
  Trajectory,
  Verification,
} from "./api";

type Destination =
  | "run"
  | "qa"
  | "compare"
  | "environments"
  | "evaluations"
  | "guards";
interface Props {
  runs: Evaluation[];
  agents: Agent[];
  environments: Environment[];
  qa: QA | null;
  online: boolean;
  navigate: (tab: Destination) => void;
  chooseRun: (id: string) => void;
  inspect: (runId: string, episodeId: string) => void;
  exportLatest: () => void;
}
interface Preview {
  runId: string;
  episode: Episode;
  trace: Trajectory;
  verification: Verification;
}
const rate = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;
const isOracle = (run: Evaluation) =>
  run?.manifest?.baseline_uses_private_truth === true;
const suiteDescriptions: Record<string, string> = {
  smoke: "Connection-pool sanity check",
  standard: "Balanced incident distribution",
  adversarial: "Incidents with untrusted log instructions",
  heldout: "Separate public seeded distribution",
};

function RunChart({ runs }: { runs: Evaluation[] }) {
  const points = runs
    .filter((run) => run.completed_episodes > 0)
    .slice(0, 12)
    .reverse();
  const x = (i: number) =>
    points.length === 1 ? 300 : 20 + (i * 560) / (points.length - 1);
  const y = (run: Evaluation) =>
    100 - (run.success_count / run.completed_episodes) * 80;
  return (
    <div className="run-chart">
      <div className="row">
        <strong>RECORDED PASS RATE</strong>
        <span>
          <i className="legend-dot" /> Customer{" "}
          <i className="legend-dot oracle" /> Oracle baseline
        </span>
      </div>
      {points.length ? (
        <>
          <svg
            viewBox="0 0 640 120"
            role="img"
            aria-label={`Pass rates across ${points.length} recent evaluations, ordered oldest to newest`}
          >
            {[20, 60, 100].map((value, i) => (
              <g key={value}>
                <line
                  x1="20"
                  y1={value}
                  x2="580"
                  y2={value}
                  stroke="#252b3b"
                  strokeDasharray="4 4"
                />
                <text x="590" y={value + 4} fill="#94a3b8" fontSize="10">
                  {100 - i * 50}%
                </text>
              </g>
            ))}
            <polyline
              points={points.map((run, i) => `${x(i)},${y(run)}`).join(" ")}
              fill="none"
              stroke="#3b82f6"
              strokeWidth="2"
            />
            {points.map((run, i) => (
              <circle
                key={run.id}
                cx={x(i)}
                cy={y(run)}
                r="4"
                fill={isOracle(run) ? "#f59e0b" : "#60a5fa"}
              >
                <title>
                  {run.name}: {rate(run.success_count / run.completed_episodes)}
                  {isOracle(run) ? " · reference oracle" : ""}
                </title>
              </circle>
            ))}
          </svg>
          <div className="row chart-caption">
            <span>Oldest shown</span>
            <span>{points.length} evaluations · observed results</span>
            <span>Latest</span>
          </div>
        </>
      ) : (
        <div className="chart-empty">
          <Activity size={24} />
          <span>Your evaluation history will appear here.</span>
        </div>
      )}
    </div>
  );
}

export default function Dashboard({
  runs,
  agents,
  environments,
  qa,
  online,
  navigate,
  chooseRun,
  inspect,
  exportLatest,
}: Props) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [copied, setCopied] = useState(false);
  const featured = runs.find((run) => run.completed_episodes > 0);
  const featuredId = featured?.id;
  const featuredCount = featured?.completed_episodes;
  useEffect(() => {
    if (!featuredId || !featuredCount || !online) return;
    let active = true;
    async function load() {
      try {
        const episodes = await api<Episode[]>(
          `/v1/evaluations/${featuredId}/episodes?limit=1&offset=${featuredCount! - 1}`,
        );
        if (!episodes[0]) return;
        const [trace, verification] = await Promise.all([
          api<Trajectory>(`/v1/episodes/${episodes[0].id}/trajectory`),
          api<Verification>(`/v1/episodes/${episodes[0].id}/verification`),
        ]);
        if (active) {
          setPreview({
            runId: featuredId!,
            episode: episodes[0],
            trace,
            verification,
          });
          setPreviewError("");
        }
      } catch (error) {
        if (active) {
          setPreview(null);
          setPreviewError((error as Error).message);
        }
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [featuredId, featuredCount, online]);
  const current = preview?.runId === featuredId ? preview : null;
  const completed = runs.reduce((sum, run) => sum + run.completed_episodes, 0);
  const customerRuns = runs.filter((run) => !isOracle(run));
  const customerEpisodes = customerRuns.reduce(
    (sum, run) => sum + run.completed_episodes,
    0,
  );
  const customerSuccess = customerRuns.reduce(
    (sum, run) => sum + run.success_count,
    0,
  );
  const safetyFailures = runs.reduce(
    (sum, run) => sum + run.hard_failures_count,
    0,
  );
  const running = runs.filter((run) => run.status === "RUNNING").length;
  const queued = runs.filter((run) => run.status === "QUEUED").length;
  const env = environments[0];
  const metrics = [
    {
      title: "Evaluated episodes",
      value: completed.toLocaleString(),
      detail: "Latest 200 runs · includes oracle",
      icon: Layers,
    },
    {
      title: "Customer pass rate",
      value: rate(customerEpisodes ? customerSuccess / customerEpisodes : null),
      detail: `${customerEpisodes} customer episodes · excludes oracle`,
      icon: CheckCircle2,
    },
    {
      title: "Safety failures",
      value: String(safetyFailures),
      detail: "Recorded episodes with hard failures",
      icon: ShieldCheck,
    },
    {
      title: "Registered agents",
      value: String(agents.length),
      detail: `${agents.filter((agent) => agent.adapter === "http_endpoint").length} HTTP endpoints · latest 200 agents`,
      icon: Plug,
    },
    {
      title: "Active evaluations",
      value: String(running),
      detail: `${queued} queued · persistent worker queue`,
      icon: Activity,
    },
  ];
  const command =
    "uv run envforge evaluate --agent-url http://127.0.0.1:9001/agent --suite smoke --episodes 10";
  return (
    <div className="mission-control">
      <section className="mission-hero">
        <div className="hero-copy">
          <div className="hero-tags">
            <span className="badge badge-cyan">
              <span className="tiny-dot" /> AUTONOMOUS SRE
            </span>
            <span>
              <LockKeyhole size={12} /> SEALED EVALUATION EVIDENCE
            </span>
            <span className="version-tag">DETERMINISTIC SIMULATION</span>
          </div>
          <h1>EnvForge: SRE & DevOps Agent Evaluation</h1>
          <p>
            Reproducible incidents, recorded agent actions, and verifiable
            recovery. A proving ground for your next agent release.
          </p>
          <div className="capability-strip">
            <span>
              <i className="legend-dot" /> Runtime:{" "}
              <strong>v{env?.version ?? "—"}</strong>
            </span>
            <span>
              Replay QA:{" "}
              <strong className={qa?.determinism_passed ? "text-green" : ""}>
                {qa?.status === "PASS" && qa.determinism_passed
                  ? `${qa.determinism_repeats} repeats passed`
                  : (qa?.status ?? "Loading")}
              </strong>
            </span>
            <span>
              <ShieldCheck size={13} /> Separate verifier process
            </span>
            <span>
              <LockKeyhole size={13} /> Typed tool access
            </span>
          </div>
        </div>
        <div className="hero-actions">
          <button className="btn-primary" onClick={() => navigate("run")}>
            <Play size={16} /> Launch Evaluation
          </button>
          <div className="row">
            <button
              className="nav-btn outlined"
              onClick={() => navigate("run")}
            >
              <Plug size={14} /> Connect Agent
            </button>
            <button
              className="nav-btn outlined"
              disabled={!runs.length || !online}
              onClick={exportLatest}
            >
              <Download size={14} /> Export Latest
            </button>
          </div>
        </div>
      </section>

      {!online && (
        <p className="notice" role="status">
          Control plane disconnected. Previously loaded values may be stale.
        </p>
      )}
      <div className="mission-metrics">
        {metrics.map(({ title, value, detail, icon: Icon }) => (
          <article className="metric-tile" key={title}>
            <div className="row">
              <span>{title}</span>
              <Icon size={16} />
            </div>
            <strong>{value}</strong>
            <p>{detail}</p>
          </article>
        ))}
      </div>

      <div className="dashboard-columns">
        <div className="dashboard-main">
          <section className="dashboard-panel">
            <div className="panel-title">
              <div>
                <h2>
                  <Activity size={17} /> Latest Recorded Trajectory
                </h2>
                <p>
                  {featured
                    ? `${agents.find((agent) => agent.id === featured.agent_id)?.name ?? featured.agent_id} · ${featured.suite} / ${featured.tier}${current ? ` · seed ${current.episode.seed}` : ""}`
                    : "Launch an evaluation to inspect its recorded actions"}
                </p>
              </div>
              <span className="version-tag">
                {current
                  ? `${current.trace.action_history.length} ACTIONS`
                  : "AWAITING EVIDENCE"}
              </span>
            </div>
            <RunChart runs={runs} />
            {featured && isOracle(featured) && (
              <p className="oracle-note">
                <FlaskConical size={13} /> Reference oracle · uses private fault
                truth
              </p>
            )}
            {current ? (
              <div className="activity-timeline">
                {current.trace.action_history.slice(-5).map((step, i) => (
                  <button
                    key={step.action_id}
                    className="activity-step"
                    onClick={() => inspect(current.runId, current.episode.id)}
                  >
                    <span className="step-number">{step.step ?? i + 1}</span>
                    <div>
                      <span
                        className={`action-kind ${["edit_config", "restart_service", "rollback"].includes(step.tool) ? "mutation" : ""}`}
                      >
                        {[
                          "edit_config",
                          "restart_service",
                          "rollback",
                        ].includes(step.tool)
                          ? "MUTATION"
                          : step.tool === "submit_incident_report"
                            ? "REPORT"
                            : "TOOL CALL"}
                      </span>
                      <code>{step.tool}</code>
                      <small>{JSON.stringify(step.arguments)}</small>
                    </div>
                    <ArrowRight size={14} />
                  </button>
                ))}
                <div className="trajectory-result">
                  <span
                    className={
                      current.verification.success ? "text-green" : "text-amber"
                    }
                  >
                    {current.verification.success ? (
                      <CheckCircle2 size={15} />
                    ) : (
                      <XCircle size={15} />
                    )}{" "}
                    {current.verification.success
                      ? "Recovery verified"
                      : "Verification failed"}
                  </span>
                  <button
                    className="text-button"
                    onClick={() => inspect(current.runId, current.episode.id)}
                  >
                    Explore trajectory <ArrowRight size={13} />
                  </button>
                </div>
              </div>
            ) : (
              <div className="empty-state">
                {previewError ||
                  (featured
                    ? "Loading recorded evidence…"
                    : "No recorded episodes yet. Connect an agent and launch your first evaluation.")}
              </div>
            )}
          </section>

          <section className="dashboard-panel benchmark-panel">
            <div className="panel-title">
              <div>
                <h2>
                  <GitCompare size={17} /> Agent Evaluation Summary
                </h2>
                <p>
                  Observed results across the latest 200 runs. Use paired
                  comparisons for decisions.
                </p>
              </div>
              <button
                className="text-button"
                onClick={() => navigate("compare")}
              >
                Compare <ArrowRight size={13} />
              </button>
            </div>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Agent / adapter</th>
                    <th>Pass rate</th>
                    <th>Episodes</th>
                    <th>Safety failures</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.slice(0, 6).map((agent) => {
                    const results = runs.filter(
                      (run) => run.agent_id === agent.id,
                    );
                    const count = results.reduce(
                      (sum, run) => sum + run.completed_episodes,
                      0,
                    );
                    const passed = results.reduce(
                      (sum, run) => sum + run.success_count,
                      0,
                    );
                    const failures = results.reduce(
                      (sum, run) => sum + run.hard_failures_count,
                      0,
                    );
                    return (
                      <tr key={agent.id}>
                        <td>
                          <div className="agent-identity">
                            <span className="agent-avatar">
                              {agent.name.slice(0, 2).toUpperCase()}
                            </span>
                            <div>
                              <strong>{agent.name}</strong>
                              <small>
                                {agent.adapter === "reference_solver"
                                  ? "Reference oracle · private truth"
                                  : "Customer HTTP endpoint"}
                              </small>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className="text-green">
                            {rate(count ? passed / count : null)}
                          </span>
                          <div className="mini-bar">
                            <span
                              style={{
                                width: `${count ? (passed / count) * 100 : 0}%`,
                              }}
                            />
                          </div>
                        </td>
                        <td>{count}</td>
                        <td className={failures ? "text-amber" : ""}>
                          {failures}
                        </td>
                        <td>
                          <button
                            className="nav-btn outlined"
                            disabled={!results.length}
                            onClick={() => chooseRun(results[0].id)}
                          >
                            {agent.adapter === "reference_solver"
                              ? "BASELINE"
                              : "View run"}
                            <ArrowRight size={12} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!agents.length && (
                <div className="empty-state">
                  No registered agents.{" "}
                  <button
                    className="text-button"
                    onClick={() => navigate("run")}
                  >
                    Connect your first agent
                  </button>
                </div>
              )}
            </div>
            <div className="panel-footnote">
              <ShieldCheck size={14} /> Release policy: ≥30 episodes, ≥80% pass,
              and no critical safety failures.
            </div>
          </section>

          <section className="dashboard-panel">
            <div className="panel-title">
              <h2>
                <Play size={16} /> Recent Evaluations
              </h2>
              <button
                className="text-button"
                onClick={() => navigate("evaluations")}
              >
                View all <ArrowRight size={13} />
              </button>
            </div>
            <div className="recent-runs">
              {runs.slice(0, 4).map((run) => (
                <button key={run.id} onClick={() => chooseRun(run.id)}>
                  <div>
                    <strong>{run.name}</strong>
                    <small>
                      {run.suite} / {run.tier} · {run.completed_episodes}/
                      {run.total_episodes} episodes
                    </small>
                  </div>
                  <span
                    className={`badge ${run.status === "COMPLETED" ? "badge-success" : run.status === "INFRA_FAILED" ? "badge-danger" : "badge-cyan"}`}
                  >
                    {run.status.replaceAll("_", " ")}
                  </span>
                  <ArrowRight size={14} />
                </button>
              ))}
              {!runs.length && (
                <div className="empty-state">
                  Your evaluation queue is empty.
                </div>
              )}
            </div>
          </section>
        </div>

        <aside className="dashboard-secondary">
          <section className="dashboard-panel">
            <div className="panel-title">
              <h2>
                <ShieldCheck size={17} /> Verifier Assurance
              </h2>
              <span
                className={`badge ${qa?.status === "PASS" ? "badge-success" : "badge-warning"}`}
              >
                {qa?.status ?? "LOADING"}
              </span>
            </div>
            <p className="panel-description">
              Recovery, safety, and evidence are checked separately from the
              agent’s decision-making.
            </p>
            {[
              {
                title: "01 · Sustained recovery",
                text: "Checks service health across multiple simulation ticks after remediation.",
                color: "green",
              },
              {
                title: "02 · Safety invariants",
                text: "Detects protected-resource damage, unnecessary mutations, and resource budget violations.",
                color: "blue",
              },
              {
                title: "03 · Incident evidence",
                text: "Checks reported fault, affected component, and supporting diagnostic action IDs.",
                color: "amber",
              },
            ].map((stage) => (
              <div className="stage-card" key={stage.title}>
                <h3>
                  <i className={`legend-dot ${stage.color}`} />
                  {stage.title}
                </h3>
                <p>{stage.text}</p>
              </div>
            ))}
            <div className="evidence-box">
              <div className="row">
                <span>RELEASE QA EVIDENCE</span>
                <span className="text-green">
                  {qa?.status === "PASS" ? "PASS" : "PENDING"}
                </span>
              </div>
              <strong>
                {qa?.instances_tested !== undefined
                  ? `${qa.reference_successes ?? 0} / ${qa.instances_tested} reference cases`
                  : "No current QA results"}
              </strong>
              <code>
                {qa?.manifest_digest ??
                  "Generate a QA report to inspect its digest."}
              </code>
              <button className="text-button" onClick={() => navigate("qa")}>
                Inspect verifier & QA <ArrowRight size={13} />
              </button>
            </div>
          </section>
          <section className="dashboard-panel">
            <div className="panel-title">
              <div>
                <h2>
                  <Layers size={17} /> Scenario Suites
                </h2>
                <p>Reproducible incident distributions</p>
              </div>
              <span className="version-tag">
                {env?.supported_suites.length ?? 0} SUITES
              </span>
            </div>
            <div className="suite-list">
              {env?.supported_suites.map((suite, index) => (
                <button key={suite} onClick={() => navigate("environments")}>
                  <span className="suite-icon">
                    <Layers size={17} />
                  </span>
                  <div>
                    <strong>{suite}</strong>
                    <small>
                      {suiteDescriptions[suite] ?? "Seeded scenarios"}
                    </small>
                  </div>
                  <span
                    className={`badge ${index === 2 ? "badge-warning" : "badge-cyan"}`}
                  >
                    {env.supported_tiers.length} TIERS
                  </span>
                </button>
              ))}
            </div>
            <button
              className="text-button full-width"
              onClick={() => navigate("environments")}
            >
              Explore scenario catalog <ArrowRight size={13} />
            </button>
          </section>
          <section className="dashboard-panel guard-summary">
            <div className="panel-title">
              <h2>
                <LockKeyhole size={16} /> Safety Guard Results
              </h2>
            </div>
            <p className="panel-description">
              Automated exploit probes against the simulation verifier.
            </p>
            {qa?.exploit_checks ? (
              Object.entries(qa.exploit_checks).map(([name, passed]) => (
                <div className="guard-result" key={name}>
                  <span>{name.replaceAll("_", " ")}</span>
                  {passed ? (
                    <CheckCircle2 size={14} className="text-green" />
                  ) : (
                    <XCircle size={14} className="text-amber" />
                  )}
                </div>
              ))
            ) : (
              <p className="panel-description">
                Run release QA to populate these checks.
              </p>
            )}
            <button
              className="text-button full-width"
              onClick={() => navigate("guards")}
            >
              View safety boundaries <ArrowRight size={13} />
            </button>
          </section>
        </aside>
      </div>
      <div className="cli-strip">
        <span>
          <Terminal size={17} /> CLI QUICK LAUNCH
        </span>
        <code>{command}</code>
        <button
          className="icon-button"
          aria-label="Copy CLI command"
          onClick={() => {
            void navigator.clipboard
              .writeText(command)
              .then(() => setCopied(true))
              .catch(() => setCopied(false));
          }}
        >
          {copied ? <CheckCircle2 size={16} /> : <Copy size={16} />}
        </button>
        <span role="status">{copied ? "Copied" : ""}</span>
      </div>
    </div>
  );
}
