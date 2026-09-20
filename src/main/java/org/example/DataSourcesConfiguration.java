package org.example;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import org.springframework.beans.factory.support.AbstractBeanDefinition;
import org.springframework.beans.factory.support.BeanDefinitionBuilder;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.boot.context.properties.bind.BindHandler;
import org.springframework.boot.context.properties.bind.Bindable;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.context.properties.bind.handler.NoUnboundElementsBindHandler;
import org.springframework.context.EnvironmentAware;
import org.springframework.core.env.Environment;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.ImportBeanDefinitionRegistrar;
import org.springframework.core.type.AnnotationMetadata;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.util.Map;

/**
 * Registers one DataSource bean per entry under {@code app.datasources}.
 * Because each pool is an ordinary DataSource bean, Spring Boot closes it on
 * shutdown, adds it to /actuator/health and publishes its hikaricp.* metrics,
 * and callers inject it with {@code @Qualifier("orders-db")} or take all of
 * them as {@code Map<String, DataSource>}.
 *
 * {@code app.pooling=none} swaps HikariCP for a DriverManagerDataSource, which
 * opens a new physical connection per request. That is never what you want in
 * production; it exists so the cost of unpooled PostgreSQL connections can be
 * measured against the pooled setups.
 *
 * An ImportBeanDefinitionRegistrar (rather than a BeanDefinitionRegistryPostProcessor)
 * so the pools exist before Boot's auto-configuration evaluates its DataSource
 * conditions; otherwise Boot would add its own default pool alongside them.
 */
@Configuration(proxyBeanMethods = false)
@Import(DataSourcesRegistrar.class)
class DataSourcesConfiguration {
}

class DataSourcesRegistrar implements ImportBeanDefinitionRegistrar, EnvironmentAware {

    private Environment environment;

    @Override
    public void setEnvironment(Environment environment) {
        this.environment = environment;
    }

    @Override
    public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry) {
        Binder binder = Binder.get(environment);
        Map<String, HikariConfig> configs = binder
                .bind("app.datasources", Bindable.mapOf(String.class, HikariConfig.class),
                        new NoUnboundElementsBindHandler(BindHandler.DEFAULT))
                .orElseThrow(() -> new IllegalStateException("No pools defined under app.datasources"));
        String primary = binder.bind("app.primary-datasource", String.class).orElse(null);
        boolean pooled = !"none".equalsIgnoreCase(binder.bind("app.pooling", String.class).orElse("hikari"));

        if (primary != null && !configs.containsKey(primary)) {
            throw new IllegalStateException("app.primary-datasource '" + primary
                    + "' is not one of " + configs.keySet());
        }

        configs.forEach((name, config) -> {
            config.setPoolName(name);
            AbstractBeanDefinition definition = pooled
                    ? BeanDefinitionBuilder
                        .genericBeanDefinition(HikariDataSource.class, () -> new HikariDataSource(config))
                        .setDestroyMethodName("close")
                        .setPrimary(name.equals(primary))
                        .getBeanDefinition()
                    : BeanDefinitionBuilder
                        .genericBeanDefinition(DriverManagerDataSource.class, () -> new DriverManagerDataSource(
                                config.getJdbcUrl(), config.getUsername(), config.getPassword()))
                        .setPrimary(name.equals(primary))
                        .getBeanDefinition();
            registry.registerBeanDefinition(name, definition);
        });
    }
}
