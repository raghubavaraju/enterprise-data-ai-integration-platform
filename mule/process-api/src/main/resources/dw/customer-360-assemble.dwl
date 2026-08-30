%dw 2.0
output application/json skipNullOn="everywhere"

/*
 * Assemble the Customer 360 business object from the system-API responses.
 *
 * Three things this transformation is responsible for, none of which belong
 * anywhere else:
 *
 *   1. Translating warehouse column names into the canonical business
 *      vocabulary.  The database's naming convention must not reach a consumer,
 *      or every future column rename becomes a breaking API change.
 *
 *   2. Reporting degradation honestly.  `partial` and `degradedFields` are
 *      populated from vars.degradedFields, which each scatter-gather route
 *      appended to when its dependency failed.
 *
 *   3. Publishing provenance: which sources actually contributed, how complete
 *      the profile is, and when the underlying row was last rebuilt.  A consumer
 *      that cannot tell "absent" from "unavailable" from "stale" will eventually
 *      make a decision on one while believing it is another.
 */

var core   = vars.core
var orders = vars.parts[0] default {data: []}
var cases  = vars.parts[1] default {data: []}
var churn  = vars.parts[2]
---
{
    customerId: core.CUSTOMER_ID,

    profile: {
        fullName:         core.FULL_NAME,
        email:            core.EMAIL,
        phone:            core.PHONE,
        birthDate:        core.BIRTH_DATE,
        segment:          core.CUSTOMER_SEGMENT,
        status:           core.CUSTOMER_STATUS,
        preferredChannel: core.PREFERRED_CHANNEL,
        marketingOptIn:   core.MARKETING_OPT_IN,
        customerSince:    core.CUSTOMER_SINCE,
        tenureDays:       core.TENURE_DAYS,
        location: {
            city:    core.PRIMARY_CITY,
            state:   core.PRIMARY_STATE,
            country: core.PRIMARY_COUNTRY
        }
    },

    orders:          orders.data default [],
    orderPagination: orders.pagination,
    support:         cases.data default [],

    loyalty: {
        tier:          core.LOYALTY_TIER,
        status:        core.LOYALTY_STATUS,
        pointsBalance: core.LOYALTY_POINTS_BALANCE,
        enrolledAt:    core.LOYALTY_ENROLLED_AT
    },

    analytics: {
        totalOrders:           core.TOTAL_ORDERS,
        totalNetRevenue:       core.TOTAL_NET_REVENUE,
        avgOrderValue:         core.AVG_ORDER_VALUE,
        orderFrequencyPerYear: core.ORDER_FREQUENCY_PER_YEAR,
        lastOrderDate:         core.LAST_ORDER_DATE,
        daysSinceLastOrder:    core.DAYS_SINCE_LAST_ORDER,
        revenueLast365d:       core.REVENUE_LAST_365D,
        returnRate:            core.RETURN_RATE,
        totalCases:            core.TOTAL_CASES,
        openCases:             core.OPEN_CASES,
        avgCsat:               core.AVG_CSAT,
        topCaseType:           core.TOP_CASE_TYPE,
        engagementScore:       core.ENGAGEMENT_SCORE,
        /* Realised value and predicted value are different numbers and are
           never merged into one field: conflating them is how a forecast ends
           up quoted in a board pack as revenue. */
        customerLifetimeValue: core.CUSTOMER_LIFETIME_VALUE,
        predictedClv12m:       core.PREDICTED_CLV_12M,
        valueTier:             core.VALUE_TIER
    },

    churnRisk: if (churn == null) null else {
        churnProbability: churn.CHURN_PROBABILITY,
        riskBand:         churn.CHURN_RISK_BAND,
        model: {
            name:              churn.MODEL_NAME,
            version:           churn.MODEL_VERSION,
            method:            churn.SCORING_METHOD,
            featureSetVersion: churn.FEATURE_SET_VERSION
        },
        drivers: [1, 2, 3]
            map (n) -> {
                rank: n,
                driver:       churn["TOP_DRIVER_" ++ n],
                contribution: churn["TOP_DRIVER_" ++ n ++ "_CONTRIB"]
            }
            filter ($.driver != null),
        scoreDate: churn.SCORE_DATE
    },

    aiInsights: vars.aiInsights,

    dataQuality: {
        completenessScore:   core.DATA_COMPLETENESS_SCORE,
        contributingSources: (core.CONTRIBUTING_SOURCES default "") splitBy ",",
        asOf:                core.AS_OF_TIMESTAMP
    },

    partial:        sizeOf(vars.degradedFields default []) > 0,
    degradedFields: vars.degradedFields default [],
    correlationId:  correlationId
}
