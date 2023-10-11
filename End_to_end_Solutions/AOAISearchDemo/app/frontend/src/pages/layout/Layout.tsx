import { Outlet, Link } from "react-router-dom";

import github from "../../assets/github.svg";

import styles from "./Layout.module.css";

const Layout = () => {
    return (
        <div className={styles.layout}>
            <header className={styles.header} role={"banner"}>
                <div className={styles.headerContainer}>
                    <Link reloadDocument to="/" className={styles.headerTitleContainer}>
                        <h3 className={styles.headerTitle}>CLUMIT + GPT | Sample</h3>
                    </Link>
                    <nav>
                    </nav>
                </div>
            </header>

            <Outlet />
        </div>
    );
};

export default Layout;
