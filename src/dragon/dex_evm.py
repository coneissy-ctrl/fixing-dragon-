        self._pair_capability_ttl = max(2.0, float(os.getenv("DEX_PAIR_CAPABILITY_TTL_SECONDS", "15")))
        self._native_rate_cache: dict[tuple, tuple[float, Decimal]] = {}
        self._gas_cache: dict[int, tuple[float, int]] = {}
        self._quote_cache_ttl = max(0.0, float(os.getenv("DEX_QUOTE_CACHE_SECONDS", "0.25")))
        self.deadline_seconds = max(5, int(os.getenv("DEX_DEADLINE_SECONDS", "20")))
        self.multicall_enabled = os.getenv("DEX_MULTICALL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.route_intermediates_enabled = False  # Hard-lock direct single-hop legs
        self.gas_limit = max(100_000, int(os.getenv("DEX_GAS_LIMIT", "300000")))
        self.flash_loan_pool = os.getenv("DEX_AAVE_POOL_ADDRESS", "").strip() or "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"

        wanted = chain_ids if chain_ids is not None else env_chain_ids()
        for cid in wanted:
            spec = get_spec(cid)
            if spec is None or spec.family != "evm":
                continue
            urls = rpc_urls(spec)
            if not urls:
                logging.warning("chain %s enabled but no RPC configured via %s; skipping", spec.name, spec.rpc_env)
                continue
            try:
                pool = RpcPool(spec, urls)