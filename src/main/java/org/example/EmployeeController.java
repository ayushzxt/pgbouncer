package org.example;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import javax.sql.DataSource;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RestController
class EmployeeController {

    private final Map<String, JdbcClient> clients;

    // One JdbcClient per pool, keyed by pool name (hikaricp-1, hikaricp-2, ...).
    EmployeeController(Map<String, DataSource> pools) {
        this.clients = pools.entrySet().stream()
                .collect(Collectors.toUnmodifiableMap(
                        Map.Entry::getKey, e -> JdbcClient.create(e.getValue())));
    }

    private static final String SELECT =
            "SELECT id, name, email, department, dbname, created_at FROM employees ORDER BY id";

    // pg_sleep joined into the same statement so one connection is held for the whole
    // workMs, which is what makes pool contention measurable. Two separate statements
    // would return the connection to the pool in between and measure nothing.
    private static final String SELECT_HOLDING_CONNECTION =
            "SELECT e.id, e.name, e.email, e.department, e.dbname, e.created_at"
                    + " FROM employees e, pg_sleep(?) ORDER BY e.id";

    private static final int MAX_WORK_MS = 10_000;

    // dbName only selects a pool from the configured set, so it never reaches the SQL.
    // workMs simulates query duration: the connection stays checked out that long.
    @GetMapping("/api/{dbName}/employees")
    List<Map<String, Object>> employees(@PathVariable String dbName,
                                        @RequestParam(defaultValue = "0") int workMs) {
        JdbcClient jdbc = clients.get(dbName);
        if (jdbc == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "Unknown database '" + dbName + "', expected one of " + clients.keySet());
        }
        if (workMs <= 0) {
            return jdbc.sql(SELECT).query().listOfRows();
        }
        if (workMs > MAX_WORK_MS) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "workMs must be <= " + MAX_WORK_MS);
        }
        return jdbc.sql(SELECT_HOLDING_CONNECTION)
                .param(workMs / 1000.0)
                .query()
                .listOfRows();
    }
}
