package org.example;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
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

    // dbName only selects a pool from the configured set, so it never reaches the SQL.
    @GetMapping("/api/{dbName}/employees")
    List<Map<String, Object>> employees(@PathVariable String dbName) {
        JdbcClient jdbc = clients.get(dbName);
        if (jdbc == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "Unknown database '" + dbName + "', expected one of " + clients.keySet());
        }
        return jdbc.sql("SELECT id, name, email, department, dbname, created_at FROM employees ORDER BY id")
                .query()
                .listOfRows();
    }
}
