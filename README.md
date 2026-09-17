# PoolKeeperBoot

A small **Spring Boot** application that shows how to connect to **several databases at the same time**.
Each database is set up in one config file, `application.yml`, and gets its own **connection pool**.

This README explains the project one file at a time, in plain language.

---

## 1. Background ideas

| Term | Meaning |
|---|---|
| **Database connection** | An open line between your Java program and a database. Opening one is slow. |
| **Connection pool** | A set of connections that are opened once and then reused. Code borrows a connection, uses it, and gives it back. |
| **HikariCP** | The connection-pool library that Spring Boot uses by default. `HikariDataSource` is its pool class. |
| **DataSource** | The standard Java interface for "something that gives me database connections". A `HikariDataSource` is one. |
| **Bean** | An object that Spring creates and manages for you. Other classes can ask Spring for it, which is called *injection*. |
| **H2** | A small database that runs inside your Java program, in memory. You don't need to install anything, which makes it good for demos. |
| **Actuator** | A Spring Boot add-on that gives you web URLs for checking the app's health and statistics. |

**What this project does:** normally Spring Boot sets up **one** database pool. This project lets you list **as many
pools as you want** in `application.yml`. Each one becomes a normal Spring bean named after its entry.

---

## 2. Project layout

```
PoolKeeperBoot/
├── pom.xml                                   ← build file: lists the libraries
├── src/main/java/org/example/
│   ├── PoolKeeperBootApplication.java        ← program entry point (main method)
│   ├── DataSourcesConfiguration.java         ← reads the YAML and creates one pool per database
│   └── Demo.java                             ← runs once at startup and tests each pool
├── src/main/resources/
│   └── application.yml                       ← settings: which databases to connect to
├── src/test/java/org/example/
│   └── PoolKeeperBootApplicationTests.java   ← automated tests
│
├── .classpath, .project, .settings/          ← Eclipse IDE files (not part of the app)
└── .github/modernize/...                     ← tool files from a Java-upgrade assistant (not part of the app)
```

---

## 3. What happens when the app starts

```
main()  ──►  Spring Boot starts
               │
               ├─► DataSourcesRegistrar reads app.datasources from application.yml
               │       and creates one pool bean for each entry: "orders-db", "reporting-db"
               │
               ├─► Spring Boot sees that DataSources already exist, so it does NOT create its own default one.
               │   It builds JdbcClient and transaction support on the pool marked "primary" (orders-db).
               │
               ├─► Actuator adds /actuator/health and /actuator/metrics
               │
               ├─► Demo.run() runs once: it writes and reads a row in each database and prints the pool stats
               │
               └─► The web server keeps running on http://localhost:8080 until you stop it (Ctrl+C).
                   When it stops, Spring closes every pool.
```

---

## 4. File by file

### 4.1 `pom.xml` (the Maven build file)

Maven is the build tool. This file tells it which libraries to download and how to package the app.

| Part | What it does |
|---|---|
| `<parent> spring-boot-starter-parent 3.5.15` | Uses Spring Boot 3.5.15. It picks library versions that work together, so the dependencies below don't need version numbers. |
| `<java.version>21</java.version>` | The project needs **Java 21**. |
| `spring-boot-starter-jdbc` | Database access support. It includes **HikariCP** and `JdbcClient`. |
| `spring-boot-starter-web` | A built-in web server (Tomcat), which serves the Actuator URLs. |
| `spring-boot-starter-actuator` | The health and metrics URLs. |
| `h2` (scope `runtime`) | The in-memory database driver used by the demo. |
| `postgresql` (commented out) | An example. Uncomment it if you want to connect to a real PostgreSQL database. |
| `spring-boot-starter-test` (scope `test`) | JUnit, AssertJ and other test tools, used only when running tests. |
| `spring-boot-maven-plugin` | Lets you run the app with `mvn spring-boot:run` and build a runnable `.jar`. |

---

### 4.2 `PoolKeeperBootApplication.java` (the entry point)

```java
@SpringBootApplication
public class PoolKeeperBootApplication {
    public static void main(String[] args) {
        SpringApplication.run(PoolKeeperBootApplication.class, args);
    }
}
```

- `main` is where the program starts, like in any Java program.
- `@SpringBootApplication` tells Spring: *"scan this package (`org.example`) for my classes and switch on auto-configuration."*
  That's how Spring finds `DataSourcesConfiguration` and `Demo` without you creating them yourself.

---

### 4.3 `application.yml` (the settings file)

This is where you **list your databases**. Here is what each section means:

```yaml
app:
  primary-datasource: orders-db      # (optional) the "default" pool
  datasources:                       # every entry below becomes one connection pool
    orders-db:                       # ← this name becomes the bean name AND the pool name
      jdbc-url: jdbc:h2:mem:ordersdb;DB_CLOSE_DELAY=-1
      username: sa
      password: ""
      maximum-pool-size: 5           # at most 5 open connections
      minimum-idle: 1                # keep at least 1 connection ready
    reporting-db:
      jdbc-url: jdbc:h2:mem:reportingdb;DB_CLOSE_DELAY=-1
      ...
      idle-timeout: 900000           # close unused connections after 15 minutes (value is in ms)
```

Notes:

- **`jdbc-url`** is the database address.
  - `jdbc:h2:mem:ordersdb` means "an H2 database named `ordersdb` held in memory".
  - `DB_CLOSE_DELAY=-1` keeps the in-memory database alive while the program runs, even if no connection is open.
    Without it, H2 deletes the database when the last connection closes.
- **The settings under each database are HikariCP settings**, written in kebab-case: `maximum-pool-size`,
  `minimum-idle`, `idle-timeout`, `connection-timeout`, and so on. Any HikariCP setting can go here.
- **A misspelled setting stops the app from starting.** For example, `max-pool-size` instead of `maximum-pool-size` causes an error.
  This is intentional: a typo would otherwise be ignored without any warning.
- **`primary-datasource`** marks one pool as the default. Spring Boot's own tools (`JdbcClient`, `JdbcTemplate`,
  `@Transactional`) use this pool when you don't name one.
- **`data-source-properties`** (see the commented `payments-db` example) passes extra settings straight to the database driver, such as `ssl: true`.
- **Passwords:** `${PAYMENTS_DB_PASSWORD}` means "read this value from an environment variable". Don't write real passwords in the file.

To **add a database**, add another entry under `datasources:`. You don't need to change any Java code.
If the database isn't H2, also add its driver to `pom.xml`.

The `management:` section configures Actuator:

```yaml
management:
  endpoints.web.exposure.include: health,metrics   # which URLs are available
  endpoint.health.show-details: always             # show every pool's status, not just "UP"
```

---

### 4.4 `DataSourcesConfiguration.java` (the configuration class)

This file turns the YAML list into real connection pools. It contains **two classes**.

#### a) `DataSourcesConfiguration`

```java
@Configuration(proxyBeanMethods = false)
@Import(DataSourcesRegistrar.class)
class DataSourcesConfiguration { }
```

This class has an empty body. Its only job is to tell Spring:
*"while you start up, also run `DataSourcesRegistrar`."*
(`proxyBeanMethods = false` is a small speed-up. You can ignore it.)

#### b) `DataSourcesRegistrar` (the part that creates the pools)

It implements two Spring interfaces:

- `EnvironmentAware`: Spring calls `setEnvironment(...)` and passes in the loaded settings, including `application.yml`.
- `ImportBeanDefinitionRegistrar`: Spring calls `registerBeanDefinitions(...)`, and this method registers the pool beans.

Here is what `registerBeanDefinitions` does, step by step:

```java
Binder binder = Binder.get(environment);
```
1. Gets a **Binder**, a Spring Boot helper that turns YAML settings into Java objects.

```java
Map<String, HikariConfig> configs = binder.bind("app.datasources",
        Bindable.mapOf(String.class, HikariConfig.class),
        new NoUnboundElementsBindHandler(BindHandler.DEFAULT))
    .orElseThrow(...);
```
2. Reads the `app.datasources` section into a map:
   `"orders-db" → HikariConfig{jdbcUrl=..., maximumPoolSize=5, ...}`, and the same for `reporting-db`.
   - `NoUnboundElementsBindHandler` is what **reports misspelled settings as an error** (see 4.3).
   - `orElseThrow` stops the app if no databases are listed.

```java
String primary = binder.bind("app.primary-datasource", String.class).orElse(null);
if (primary != null && !configs.containsKey(primary)) throw ...
```
3. Reads the optional primary pool name and checks that it matches one of the listed databases.

```java
configs.forEach((name, config) -> {
    config.setPoolName(name);
    AbstractBeanDefinition definition = BeanDefinitionBuilder
        .genericBeanDefinition(HikariDataSource.class, () -> new HikariDataSource(config))
        .setDestroyMethodName("close")
        .setPrimary(name.equals(primary))
        .getBeanDefinition();
    registry.registerBeanDefinition(name, definition);
});
```
4. For **each** database:
   - Gives the pool the same name as its entry, so logs and metrics say `orders-db`.
   - Describes a bean for Spring (a **bean definition**):
     - *how to create it*: `new HikariDataSource(config)`
     - *how to clean it up*: call `close()` when the app stops
     - *whether it's the primary pool*
   - Registers that definition under the entry's name, for example `"orders-db"`.

**Why use a "registrar" instead of a normal `@Bean` method?**
A `@Bean` method has a fixed name and there's one per method, so it can't create a variable number of beans from a list.
A registrar can. It also runs **early**, before Spring Boot's auto-configuration checks whether a DataSource exists.
Spring Boot then sees the pools and **doesn't create an extra default pool**.

**Why is this useful?** Each pool is an ordinary Spring bean, so Spring Boot automatically:
- closes each pool on shutdown
- shows each pool in `/actuator/health`
- publishes `hikaricp.*` metrics for each pool
- lets other classes ask for pools by name (see `Demo.java`)

---

### 4.5 `Demo.java` (the CommandLineRunner)

#### What is a `CommandLineRunner`?

It's a Spring interface with one method, `run(String... args)`.
**Spring calls `run` once, automatically, right after the app has finished starting.**
You never call it yourself. Use it for code that should run once at startup, such as a demo, sample data, or a check.
(`args` holds the command-line arguments that were passed to `main`. This demo doesn't use them.)

```java
@Component
class Demo implements CommandLineRunner {
```
`@Component` tells Spring to create this object. Spring sees that it implements `CommandLineRunner` and calls `run` later.

#### The constructor (how the pools are injected)

```java
Demo(Map<String, DataSource> pools, @Qualifier("reporting-db") DataSource reportingDb)
```
Spring fills in these parameters for you:
- `Map<String, DataSource> pools` receives **all** DataSource beans, keyed by name:
  `{"orders-db" → pool, "reporting-db" → pool}`.
- `@Qualifier("reporting-db") DataSource reportingDb` receives **only the pool named `reporting-db`**.

`JdbcClient.create(reportingDb)` wraps that pool in `JdbcClient`, Spring's tool for running SQL.

#### The `run` method

```java
System.out.println("Registered pools: " + pools.keySet());
```
1. Prints the names of the pools.

For **each** pool:
```java
jdbc.sql("CREATE TABLE IF NOT EXISTS notes(id INT PRIMARY KEY, note VARCHAR(100))").update();
jdbc.sql("MERGE INTO notes KEY(id) VALUES (1, ?)").param("from pool " + name).update();
String note = jdbc.sql("SELECT note FROM notes WHERE id = 1").query(String.class).single();
```
2. Creates a `notes` table, inserts or updates row 1 with the text `"from pool <name>"`, and reads it back.
   Each pool points to a **separate** database, so each prints its own text.
   (`MERGE INTO ... KEY(...)` is H2 syntax. On PostgreSQL you'd write `INSERT ... ON CONFLICT`.)

```java
var mx = ((HikariDataSource) ds).getHikariPoolMXBean();
... mx.getActiveConnections(), mx.getIdleConnections(), mx.getTotalConnections()
```
3. Prints live pool statistics: connections **in use** (active), connections **waiting** (idle), and the **total**.

```java
String note = reporting.sql("SELECT note FROM notes WHERE id = 1")...
```
4. Reads the row again through the `@Qualifier` pool. This shows that the pool injected by name is the `reporting-db` database.

#### Expected output (roughly)

```
Registered pools: [orders-db, reporting-db]
[orders-db] query result: from pool orders-db
[orders-db] active=0 idle=1 total=1
[reporting-db] query result: from pool reporting-db
[reporting-db] active=0 idle=1 total=1
Via @Qualifier("reporting-db"): from pool reporting-db
```

---

### 4.6 `PoolKeeperBootApplicationTests.java` (automated tests)

`@SpringBootTest` starts the whole application inside the test, then checks it:

| Test | What it checks |
|---|---|
| `registersEveryConfiguredPoolWithItsSettings` | Exactly two pools exist (`orders-db`, `reporting-db`), and their YAML settings were applied (pool size 5, idle timeout 900000). |
| `autoConfiguredJdbcClientUsesPrimaryPool` | The `JdbcClient` that Spring Boot creates by default connects to `ordersdb`, the **primary** pool. |
| `misspelledPoolPropertyFailsStartup` | Starts the app with the misspelled setting `max-pool-size` and checks that **startup fails** with an error that names the bad setting. |

The arguments that start with `--` in the last test are command-line overrides.
`--app.datasources.orders-db.max-pool-size=3` works like adding that line to `application.yml`.

---

### 4.7 Files that aren't part of the app

| File | What it is |
|---|---|
| `.classpath`, `.project`, `.settings/*` | Project settings created by the **Eclipse / Spring Tools** IDE. The app doesn't use them. |
| `.github/modernize/java-upgrade/...` | Files from a VS Code "Java upgrade" assistant. The scripts record which tools the assistant used. The app doesn't use them. |

You can ignore all of these.

---

## 5. How to run

You need **Java 21** and **Maven** installed. (No database needed, because H2 runs in memory.)

```bash
# run the app
mvn spring-boot:run

# run the tests
mvn test

# or build a jar and run it
mvn package
java -jar target/PoolKeeperBoot-1.0-SNAPSHOT.jar
```

While the app is running, open these URLs in your browser:

| URL | Shows |
|---|---|
| http://localhost:8080/actuator/health | `UP`/`DOWN` status for each database |
| http://localhost:8080/actuator/metrics | A list of available metrics, including `hikaricp.connections.*` |
| http://localhost:8080/actuator/metrics/hikaricp.connections.active?tag=pool:orders-db | Active connections for a single pool |

Press **Ctrl+C** to stop the app. Every pool is closed cleanly.

### Changing settings from the command line

Any YAML setting can be overridden with `--setting=value`:

```bash
java -jar target/PoolKeeperBoot-1.0-SNAPSHOT.jar --app.datasources.orders-db.maximum-pool-size=10
```

---

## 6. Using a pool in your own code

```java
@Service
class OrderService {
    private final JdbcClient orders;
    OrderService(@Qualifier("orders-db") DataSource ds) {   // ask for a pool by its YAML name
        this.orders = JdbcClient.create(ds);
    }
}
```

If you don't name a pool, you get the primary one:

```java
@Service
class DefaultService {
    DefaultService(JdbcClient jdbc) { ... }   // uses orders-db (the primary-datasource)
}
```
