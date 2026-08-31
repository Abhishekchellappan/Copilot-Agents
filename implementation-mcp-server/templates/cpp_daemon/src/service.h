/**
 * @file service.h
 * @brief {COMPONENT_NAME} — Service Class Declaration
 *
 * Copyright (c) 2026 LG Electronics Inc.
 * All rights reserved.
 */

#ifndef {COMPONENT_NAME_UPPER}_SERVICE_H_
#define {COMPONENT_NAME_UPPER}_SERVICE_H_

#include <string>
#include <memory>

/**
 * @class {COMPONENT_NAME_PASCAL}Service
 * @brief Main service class for {COMPONENT_NAME}
 */
class {COMPONENT_NAME_PASCAL}Service {
public:
    {COMPONENT_NAME_PASCAL}Service();
    ~{COMPONENT_NAME_PASCAL}Service();

    /** @brief Initialize the service and register IPC endpoints */
    bool initialize();

    /** @brief Start the main processing loop */
    void run();

    /** @brief Gracefully stop the service */
    void stop();

private:
    bool m_isRunning = false;
    // TODO: Add component-specific member variables
};

#endif  // {COMPONENT_NAME_UPPER}_SERVICE_H_
