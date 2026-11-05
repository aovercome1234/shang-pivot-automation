package com.shangpivot.common.util;

import cn.hutool.core.util.IdUtil;
import cn.hutool.core.util.StrUtil;
import org.slf4j.MDC;

public final class TraceIdUtil {
    public static final String HEADER = "X-Trace-Id";
    public static final String HEADER_PERF_RUN_ID = "X-Perf-Run-Id";
    public static final String HEADER_PERF_SCENARIO = "X-Perf-Scenario";
    public static final String MDC_KEY = "traceId";
    public static final String MDC_USER_ID = "userId";
    public static final String MDC_USERNAME = "username";
    public static final String MDC_PERF_RUN_ID = "perfRunId";
    public static final String MDC_PERF_SCENARIO = "perfScenario";

    private TraceIdUtil() {}

    public static String get() {
        String id = MDC.get(MDC_KEY);
        return StrUtil.isBlank(id) ? "" : id;
    }

    public static String getOrCreate(String incoming) {
        if (StrUtil.isNotBlank(incoming)) {
            return incoming;
        }
        return IdUtil.fastSimpleUUID();
    }

    public static void set(String traceId) {
        MDC.put(MDC_KEY, traceId);
    }

    public static void setUser(Long userId, String username) {
        if (userId != null) {
            MDC.put(MDC_USER_ID, String.valueOf(userId));
        }
        if (StrUtil.isNotBlank(username)) {
            MDC.put(MDC_USERNAME, username);
        }
    }

    /** 压测上下文：k6 注入的 run/scenario 只进入日志 MDC，不影响业务 traceId。 */
    public static void setPerfContext(String runId, String scenario) {
        if (StrUtil.isNotBlank(runId)) {
            MDC.put(MDC_PERF_RUN_ID, runId);
        }
        if (StrUtil.isNotBlank(scenario)) {
            MDC.put(MDC_PERF_SCENARIO, scenario);
        }
    }

    public static String userId() {
        String v = MDC.get(MDC_USER_ID);
        return StrUtil.blankToDefault(v, "-");
    }

    public static String username() {
        String v = MDC.get(MDC_USERNAME);
        return StrUtil.blankToDefault(v, "-");
    }

    public static void clear() {
        MDC.remove(MDC_KEY);
        MDC.remove(MDC_USER_ID);
        MDC.remove(MDC_USERNAME);
        MDC.remove(MDC_PERF_RUN_ID);
        MDC.remove(MDC_PERF_SCENARIO);
    }
}
