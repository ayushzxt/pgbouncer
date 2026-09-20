package org.example;

import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.server.ResponseStatusException;

import javax.sql.DataSource;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
class PoolKeeperBootApplicationTests {

    @Autowired
    Map<String, DataSource> pools;

    @Autowired
    JdbcClient primaryJdbcClient;

    @Test
    void registersEveryConfiguredPoolWithItsSettings() {
        assertThat(pools).containsOnlyKeys("orders-db", "reporting-db");
        HikariDataSource orders = (HikariDataSource) pools.get("orders-db");
        assertThat(orders.getPoolName()).isEqualTo("orders-db");
        assertThat(orders.getMaximumPoolSize()).isEqualTo(5);
        assertThat(((HikariDataSource) pools.get("reporting-db")).getIdleTimeout()).isEqualTo(900_000);
    }

    @Test
    void autoConfiguredJdbcClientUsesPrimaryPool() {
        String url = primaryJdbcClient.sql("SELECT DATABASE()").query(String.class).single();
        assertThat(url).isEqualToIgnoringCase("ordersdb");
    }

    @Autowired
    EmployeeController employeeController;

    @Test
    void employeesEndpointReadsFromTheRequestedPool() {
        JdbcClient reporting = JdbcClient.create(pools.get("reporting-db"));
        reporting.sql("CREATE TABLE IF NOT EXISTS employees(id INT PRIMARY KEY, name VARCHAR(100), "
                + "email VARCHAR(150), department VARCHAR(50), dbname VARCHAR(50), created_at TIMESTAMP)").update();
        reporting.sql("MERGE INTO employees KEY(id) VALUES (1, 'Alice', 'a@x', 'Eng', 'reportingdb', NOW())").update();

        var rows = employeeController.employees("reporting-db", 0);
        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).get("DBNAME")).isEqualTo("reportingdb");

        assertThatThrownBy(() -> employeeController.employees("nope", 0))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("nope");
    }

    @Test
    void misspelledPoolPropertyFailsStartup() {
        SpringApplication app = new SpringApplication(PoolKeeperBootApplication.class);
        assertThatThrownBy(() -> app.run(
                "--spring.main.web-application-type=none",
                "--app.datasources.orders-db.max-pool-size=3"))
                .hasStackTraceContaining("max-pool-size");
    }
}
