import sys


def main():
    graph_path = sys.argv[sys.argv.index("--graph") + 1]
    count = 0
    with open(graph_path, encoding="utf-8") as graph:
        for line in graph:
            if line.strip():
                count += 1
    print("AnalysisTime\t0.001")
    print(f"#SEdges\t{count}")


if __name__ == "__main__":
    main()
