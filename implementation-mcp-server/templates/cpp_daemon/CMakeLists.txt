cmake_minimum_required(VERSION 3.14)
project({COMPONENT_NAME} VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Source files
file(GLOB_RECURSE SOURCES "src/*.cpp")

add_executable(${PROJECT_NAME} ${SOURCES})

# Link libraries (add project-specific dependencies here)
target_link_libraries(${PROJECT_NAME} PRIVATE
    pthread
    # PmLogLib   # Uncomment for webOS logging
    # luna-service2  # Uncomment for Luna Bus IPC
)

install(TARGETS ${PROJECT_NAME} DESTINATION ${CMAKE_INSTALL_SBINDIR})
