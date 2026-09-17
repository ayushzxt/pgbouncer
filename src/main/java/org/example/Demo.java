package org.example;

import com.zaxxer.hikari.HikariDataSource;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.util.Map;

@Component
class Demo implements CommandLineRunner {

    private final Map<String, DataSource> pools;

    // Spring injects every DataSource bean keyed by bean (pool) name.
    Demo(Map<String, DataSource> pools) {
        this.pools = pools;
    }

    @Override
    public void run(String... args) {
        System.out.println("Registered pools: " + pools.keySet());

        pools.forEach((name, ds) -> {
            var mx = ((HikariDataSource) ds).getHikariPoolMXBean();
            System.out.printf("[%s] active=%d idle=%d total=%d%n",
                    name, mx.getActiveConnections(), mx.getIdleConnections(), mx.getTotalConnections());
        });
    }
}
