# Next Steps: Trading System v2.0 Development Roadmap

**Document Date:** February 6, 2026  
**Status:** Active  
**Priority:** High - Required for Production Readiness

---

## Executive Summary

Trading System v2.0 has a solid architectural foundation with all 5 core agents implemented and functioning. Current gap analysis identifies 8 critical action items needed to move from development to production deployment. This document prioritizes work to enable safe, observable, and compliant live trading.

---

## Critical Path (P0 - Do First)

### 1. Implement Event Calendar Integration
**Status:** ⛔ BLOCKED - Event calendar is empty  
**Impact:** HIGH - System currently ignores market holidays and earnings events  
**Effort:** 2-3 days

**Current State:**
```python
self._events: List[Dict] = []  # Hardcoded empty
```

**Actions:**
- [ ] Connect to NSE holiday calendar (integrate with yoptions or pandas_datareader)
- [ ] Add earnings date detection for NIFTY/BANKNIFTY stocks
- [ ] Populate RBI rate decision dates and macro event calendar
- [ ] Create `/backend/data/events_calendar.json` with next 12 months of events
- [ ] Implement cache refresh (weekly sync from external source)
- [ ] Add event_flag validation to Sentinel output logging
- [ ] **Test:** Verify system blackouts on RBI announcement dates

**Files to Modify:**
- `backend/app/services/sentinel.py` - `_check_events()` method
- `backend/app/config/constants.py` - Add EVENT_SOURCES constant
- Create: `backend/scripts/sync_event_calendar.py`

**Success Criteria:**
- Event blackouts prevent trade entry on known event dates
- System logs show "Event blackout active" for applicable dates

---

### 2. Add Comprehensive Unit Tests
**Status:** ⛔ MISSING - Zero test files  
**Impact:** HIGH - No safety net for critical calculations  
**Effort:** 5-7 days

**Current Testing Gap:**
- Regime classification (Sentinel) has 10+ metrics, untested
- Risk calculations (Treasury) validate every trade, untested
- Order execution (Executor) handles multi-leg trades, untested
- Greeks calculations completely untested
- Portfolio position tracking untested

**Actions:**
- [ ] Create test structure: `backend/tests/` directory
- [ ] Write unit tests for Sentinel regime classification:
  - Test ADX/RSI/ATR calculations
  - Test confluence scoring logic
  - Test regime boundaries (RANGE_BOUND → CAUTION transitions)
  - Test ML classifier override conditions
- [ ] Write unit tests for Treasury risk validation:
  - Test margin calculation and limits
  - Test circuit breaker logic
  - Test drawdown multipliers
  - Test Greek limits enforcement
- [ ] Write unit tests for Executor order placement:
  - Test multi-leg order atomicity
  - Test order rejection/rollback
  - Test position creation
- [ ] Add integration tests for full agent pipeline (Sentinel → Strategist → Treasury)
- [ ] Set up pytest with coverage reporting (target: >80% coverage on core logic)
- [ ] Add GitHub Actions CI/CD pipeline to run tests on every commit

**Test File Structure:**
```
backend/tests/
├── unit/
│   ├── test_sentinel_regime.py
│   ├── test_treasury_risk.py
│   ├── test_executor_orders.py
│   ├── test_technical_indicators.py
│   └── test_volatility_metrics.py
├── integration/
│   ├── test_agent_pipeline.py
│   └── test_full_trading_loop.py
└── fixtures/
    └── sample_data.py
```

**Success Criteria:**
- All core logic has >80% test coverage
- Tests pass in CI/CD pipeline
- Test suite runs in <60 seconds

---

### 3. Fix Credentials Management
**Status:** ⚠️ SECURITY RISK - Credentials stored in DB without encryption  
**Impact:** CRITICAL - Production blocker  
**Effort:** 2-3 days

**Current Issues:**
```python
# Database stores credentials in plaintext
api_key = Column(String(50), nullable=False)
api_secret = Column(String(50), nullable=False)
access_token = Column(String(100), nullable=False)

# Default database URL exposed
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@...")
```

**Actions:**
- [ ] Implement encryption for credentials in database:
  - Use `cryptography` library (Fernet symmetric encryption)
  - Encrypt at rest: `api_secret`, `access_token`
  - Add `encryption_key` to `.env` (generated via `openssl rand -hex 32`)
- [ ] Remove default DATABASE_URL - fail-fast if not configured
- [ ] Migrate KiteCredentials model:
  ```python
  from cryptography.fernet import Fernet
  
  class KiteCredentials(Base):
      api_key = Column(String(50), nullable=False)  # Can be plain (non-secret)
      api_secret_encrypted = Column(String(500), nullable=False)  # Encrypted
      access_token_encrypted = Column(String(500), nullable=False)  # Encrypted
      
      def decrypt_secret(self, key: str) -> str:
          cipher = Fernet(key)
          return cipher.decrypt(self.api_secret_encrypted).decode()
  ```
- [ ] Create migration script to encrypt existing credentials
- [ ] Update `.env.example` with encryption key placeholder
- [ ] Add `.env` to `.gitignore` (ensure no secrets committed)
- [ ] Document secrets management in README

**Success Criteria:**
- All credentials encrypted in database
- System fails immediately if DATABASE_URL not configured
- No plaintext secrets in code or git history

---

### 4. Implement Proper Secrets Management Infrastructure
**Status:** ⚠️ INCOMPLETE - Hardcoded fallbacks  
**Impact:** HIGH - Production blocker  
**Effort:** 2-3 days

**Actions:**
- [ ] Create `.env.example` with all required variables:
  ```
  # Kite API
  KITE_API_KEY=<get from Zerodha>
  KITE_ACCESS_TOKEN=<get from Zerodha>
  
  # Database
  DATABASE_URL=postgresql://user:password@host:5432/trading
  
  # Encryption
  ENCRYPTION_KEY=<generate with openssl rand -hex 32>
  
  # System
  TRADING_MODE=paper|live
  LOG_LEVEL=INFO
  ```
- [ ] Add startup validation in `main.py`:
  ```python
  from ..core.config_validator import validate_config
  
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      validate_config()  # Fail fast if critical vars missing
      yield
  ```
- [ ] Use `python-dotenv` to load `.env` in development
- [ ] Document environment variable requirements in README
- [ ] Add validation: required vs optional, format checks

**Success Criteria:**
- System fails with clear error if required env vars missing
- No hardcoded credentials anywhere
- README documents all required environment variables

---

## High Priority (P1 - Do Soon)

### 5. Add Observability & Monitoring
**Status:** ⚠️ PARTIAL - Loguru configured but no metrics  
**Impact:** HIGH - Cannot observe live system behavior  
**Effort:** 4-5 days

**Current State:**
- Logging: ✅ Loguru configured
- Metrics: ❌ None
- Distributed tracing: ❌ None
- Health checks: ❌ None

**Actions:**
- [ ] Add Prometheus metrics:
  - Trade execution success rate
  - Regime detection frequency/distribution
  - Portfolio P&L per minute
  - Margin utilization %
  - Circuit breaker triggers
  - Position count over time
- [ ] Implement health check endpoint:
  ```python
  @app.get("/health")
  async def health_check():
      return {
          "status": "healthy",
          "kite_connected": kite.is_connected(),
          "db_connected": db.is_connected(),
          "market_hours": is_market_hours()
      }
  ```
- [ ] Set up structured logging with correlation IDs for request tracing
- [ ] Create Grafana dashboard for:
  - Real-time P&L
  - Regime distribution
  - Trade statistics
  - System health
  - Database performance
- [ ] Add performance logging for slow operations (>100ms)

**Success Criteria:**
- Prometheus metrics exposed on `/metrics`
- Grafana dashboards show system health and trading metrics
- All critical operations have correlation IDs in logs

---

### 6. Implement Circuit Breaker & API Resilience
**Status:** ⚠️ INCOMPLETE - Simple retry logic only  
**Impact:** MEDIUM - API failures can cascade  
**Effort:** 3-4 days

**Current State:**
```python
max_retries: int = 3,
retry_delay: float = 1.0  # Fixed, no backoff
```

**Actions:**
- [ ] Implement exponential backoff with jitter:
  ```python
  def _exponential_backoff_delay(attempt: int) -> float:
      base_delay = 1.0
      max_delay = 60.0
      jitter = random.random() * 0.1
      delay = min(base_delay * (2 ** attempt) + jitter, max_delay)
      return delay
  ```
- [ ] Add circuit breaker pattern for KiteConnect API calls:
  - CLOSED: Normal operation
  - OPEN: Reject requests if failure threshold exceeded
  - HALF_OPEN: Allow limited requests to test recovery
- [ ] Handle specific KiteConnect exceptions:
  - TokenExpiredException → Attempt token refresh
  - DataException → Use cached data
  - NetworkError → Retry with backoff
  - QuotaExceeded → Reduce polling frequency
- [ ] Add fallback mechanisms:
  - Use cached option chain data if API unavailable
  - Use previous regime classification if unable to fetch new data
  - Skip new trade signals if Sentinel fails
- [ ] Log all API failures and recovery attempts

**Success Criteria:**
- System recovers gracefully from temporary API failures
- No cascading failures
- Backoff delays follow exponential pattern
- Circuit breaker transitions logged

---

### 7. Enhance Error Handling & Logging for Trade Execution
**Status:** ⚠️ PARTIAL - Basic error handling exists  
**Impact:** MEDIUM - Hard to debug execution failures  
**Effort:** 2-3 days

**Current Issues:**
```python
# Executor has rollback but recovery is unclear
if success:
    # Wait for fills and create position
    self._wait_for_fills(orders)
else:
    # Rollback successful orders if partial failure
    self._rollback_orders([o for o in orders if o.status == OrderStatus.OPEN])
```

**Actions:**
- [ ] Add detailed execution logging:
  - Log each order placement with order ID
  - Log order fill updates
  - Log position creation/closure
  - Log all exit triggers with reason
- [ ] Implement order timeout handling:
  - Set timeout for order placement (30-60 seconds)
  - Set timeout for order fills (5 minutes)
  - Cancel stuck orders after timeout
- [ ] Add failure recovery procedures:
  - If multi-leg order partially fills, flatten entire position
  - If order cancellation fails, alert trader
  - Document manual intervention procedures
- [ ] Create execution audit trail:
  - Every order decision stored in database with timestamp
  - All order updates logged with broker confirmation
  - Position P&L tracked at granular level
- [ ] Add alert system for unusual execution (>2x expected slippage, etc.)

**Success Criteria:**
- Every trade decision and execution is logged
- Execution audit trail complete and queryable
- Traders can trace every order back to regime signal

---

## Medium Priority (P2 - Do Later)

### 8. Implement ML Model Versioning & Retraining
**Status:** ⚠️ INCOMPLETE - Training script exists but no production pipeline  
**Impact:** MEDIUM - ML classifier not production-ready  
**Effort:** 4-5 days

**Current State:**
```python
if self.ml_classifier and ml_probability > ML_OVERRIDE_PROBABILITY:
    regime = ml_regime  # Override if available
```

**Actions:**
- [ ] Create ML model versioning:
  - Store models in `backend/data/models/` with version timestamp
  - Track model training date and dataset
  - Store model performance metrics (accuracy, F1, etc.)
- [ ] Implement retraining pipeline:
  - Monthly retraining on rolling 12-month window
  - Cross-validation to prevent overfitting
  - A/B test new model vs. current model
  - Automatic rollback if accuracy drops
- [ ] Add model performance monitoring:
  - Track classifier precision/recall in live trading
  - Alert if drift detected (performance degrades)
  - Compare actual regimes vs. ML predictions weekly
- [ ] Document model training procedure:
  - Data requirements (OHLCV, IV, etc.)
  - Feature engineering steps
  - Model selection rationale
  - Validation methodology
- [ ] Set up scheduled retraining job:
  - Run monthly on weekend
  - Update model if performance improves
  - Store old model as fallback

**Success Criteria:**
- ML models versioned and tracked
- Retraining pipeline automated
- Model drift detected and alerted
- Fallback to rules-based classification if ML unavailable

---

### 9. Backtest Framework Integration with Live System
**Status:** ⚠️ PARTIAL - Backtest engine exists but integration unclear  
**Impact:** MEDIUM - Cannot validate new rules before deployment  
**Effort:** 3-4 days

**Actions:**
- [ ] Create backtest harness that uses real system rules:
  - Use same Sentinel regime detection logic
  - Use same Strategist signal generation
  - Use same Treasury risk validation
  - Simulate Executor with real order fills from historical data
- [ ] Implement parameter sweep analysis:
  - Test different ADX thresholds
  - Test different IV percentile levels
  - Test different position sizing formulas
  - Report optimal parameters
- [ ] Add statistical significance testing:
  - Require minimum 30 trades per parameter set
  - Calculate confidence intervals
  - Report Sharpe ratio and win rate
- [ ] Create rollback procedure:
  - Easy way to revert to previous Sentinel/Strategist rules
  - Keep version history of all rule changes
  - Document rationale for each rule change
- [ ] Generate backtest reports:
  - Return distribution
  - Drawdown analysis
  - Win rate and profit factor
  - Strategy correlation with market

**Success Criteria:**
- New rules backtested before deployment
- Backtest results reproducible
- Parameter optimization automated
- Statistical significance required for approval

---

## Infrastructure & Operations (P2)

### 10. Database Backup & Recovery Strategy
**Status:** ⛔ MISSING  
**Impact:** MEDIUM - Data loss possible  
**Effort:** 2-3 days

**Actions:**
- [ ] Implement daily database backups:
  - Daily full backup (AWS RDS backup or pg_dump)
  - Hourly incremental backups during market hours
  - Store 30 days of backups
- [ ] Test recovery procedure weekly
- [ ] Document restore procedures
- [ ] Implement point-in-time recovery (PITR)
- [ ] Add alerting for backup failures

**Success Criteria:**
- Daily backups verified to be restorable
- Recovery time < 1 hour
- Recovery tested monthly

---

### 11. API Rate Limit Management
**Status:** ⚠️ INCOMPLETE - No rate limit tracking  
**Impact:** MEDIUM - Can exceed KiteConnect limits  
**Effort:** 2 days

**Actions:**
- [ ] Track API call frequency by endpoint
- [ ] Implement call budgeting system
- [ ] Add adaptive polling:
  - Increase poll interval if approaching limits
  - Reduce data requested if rate limited
  - Prefer batch endpoints over individual calls
- [ ] Log all rate limit responses
- [ ] Alert if usage exceeds 80% of daily limit

**Success Criteria:**
- Never exceed KiteConnect API limits in live trading
- System gracefully degrades under rate limit pressure

---

### 12. Documentation & Runbook Creation
**Status:** ⚠️ PARTIAL - Theory docs exist, operational runbooks missing  
**Impact:** MEDIUM - Operational knowledge not captured  
**Effort:** 2-3 days

**Actions:**
- [ ] Create operational runbook:
  - System startup checklist
  - Daily health checks
  - Emergency procedures (manual flatten, etc.)
  - Troubleshooting guide for common issues
- [ ] Document API credentials workflow:
  - How to obtain Kite credentials
  - How to update credentials
  - What to do if token expires
- [ ] Create incident response procedures:
  - Order placement failure
  - Position stuck in execution
  - Database connection loss
  - API service outage
- [ ] Document parameter tuning procedure:
  - How to change regime thresholds
  - How to test changes in backtest
  - How to deploy changes safely
- [ ] Create quick reference guide for traders:
  - Dashboard overview
  - How to read regime signals
  - Manual intervention procedures
  - Escalation procedures

**Success Criteria:**
- New operators can start system from scratch using runbook
- All common issues have documented solutions
- Emergency procedures clear and actionable

---

## Recommended Execution Order

### Week 1: Critical Fixes (P0)
1. ✅ **Day 1-2:** Event Calendar Integration (1.0)
2. ✅ **Day 3-4:** Credentials Encryption (3.0)
3. ✅ **Day 5:** Secrets Management (4.0)

**Gate:** Code review and deployment to staging

### Week 2-3: Safety & Testing (P0-P1)
4. ✅ **Days 1-3:** Unit Tests (2.0)
5. ✅ **Days 4-5:** Circuit Breaker & API Resilience (6.0)

**Gate:** Test coverage >80%, circuit breaker tested

### Week 4: Observability (P1)
6. ✅ **Days 1-3:** Add Monitoring & Observability (5.0)
7. ✅ **Days 4-5:** Enhanced Logging (7.0)

**Gate:** Dashboards live and showing real data

### Weeks 5+: Polish & Hardening (P2)
8. ML Model Versioning (8.0)
9. Backtest Integration (9.0)
10. Infrastructure & Operations (10-12)

---

## Success Metrics

After implementing these items, system should have:

✅ **Reliability:**
- 99.5% uptime during market hours
- Zero data loss (verified backups)
- Graceful degradation under stress

✅ **Observability:**
- Full audit trail of all trades
- Real-time dashboards for P&L and risk
- Detailed logs for debugging issues

✅ **Safety:**
- All credentials encrypted
- Comprehensive test coverage (>80%)
- Circuit breakers prevent cascading failures
- Risk limits strictly enforced

✅ **Operability:**
- Runbooks for all common scenarios
- Clear error messages and alerts
- Easy parameter tuning and deployment

✅ **Compliance:**
- Complete trade audit trail
- Regulatory-compliant logging
- Documentation of all decisions

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Production data loss | Daily backups + PITR tested weekly |
| Credential compromise | Encryption at rest + audit logging |
| API rate limits exceeded | Rate limit tracking + adaptive polling |
| Order execution failure | Multi-leg atomic orders + rollback |
| Regime false positives | Confluence scoring + ML override |
| Drawdown acceleration | Circuit breakers + position sizing limits |
| System cascade failure | Circuit breaker pattern + fallbacks |

---

## Sign-Off

**Prepared By:** Code Review (Feb 6, 2026)  
**Reviewed By:** [PENDING]  
**Approved By:** [PENDING]  
**Target Completion:** March 31, 2026  

---

## Appendix: Quick Reference

### Critical Blocker Items
- [ ] Item 1.0: Event Calendar
- [ ] Item 2.0: Unit Tests
- [ ] Item 3.0: Credentials Encryption
- [ ] Item 4.0: Secrets Management

### High Impact Items
- [ ] Item 5.0: Monitoring
- [ ] Item 6.0: Circuit Breaker
- [ ] Item 7.0: Execution Logging

### Nice-to-Have Items
- [ ] Item 8.0: ML Versioning
- [ ] Item 9.0: Backtest Integration
- [ ] Item 10-12: Operations

---

**Last Updated:** February 6, 2026  
**Version:** 1.0
